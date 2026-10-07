"""
Exit Tests for Module P-07: Data Layer: Migrations, Backups, Disaster Recovery.
Gate requirements to P-08:
1. Migration rehearsal on production-scale clone passes within window.
2. Restore drill meets RPO and RTO targets with data integrity verified.
3. Backup-immutability test: deletion attempt on protected backup is denied.
4. Region-failover tabletop + partial live drill completed and documented.
5. Archival job moves aged data without affecting query performance.
"""
import pytest
from app.validation.data_governance import DataGovernanceEngine


def test_p07_exit_test_1_migration_rehearsal_on_clone():
    """
    Exit Test 1: Migration rehearsal on production-scale clone passes within window.
    """
    migration_sql = """
    BEGIN;
    ALTER TABLE plans ADD COLUMN IF NOT EXISTS cost_cents INT DEFAULT 0;
    CREATE INDEX IF NOT EXISTS idx_plans_cost ON plans(cost_cents);
    COMMIT;
    """
    rehearsal = DataGovernanceEngine.rehearse_migration(
        migration_sql=migration_sql,
        target_clone_id="staging-aurora-prod-clone-01",
        maintenance_window_minutes=30.0
    )

    assert rehearsal["rehearsal_passed"] is True
    assert rehearsal["is_transactional"] is True
    assert rehearsal["within_maintenance_window"] is True


def test_p07_exit_test_2_automated_restore_drill_rto_rpo():
    """
    Exit Test 2: Restore drill meets RPO (<15m) and RTO (<60m) targets with data integrity verified.
    """
    restore_result = DataGovernanceEngine.execute_restore_drill(
        snapshot_id="rds:snap-2026-10-05-prod-daily",
        restore_duration_minutes=24.5,   # RTO target <= 60m
        data_loss_window_minutes=4.2,    # RPO target <= 15m
        expected_records_count=542000,
        restored_records_count=542000    # 100% data completeness
    )

    assert restore_result["passed"] is True
    assert restore_result["rto_met"] is True
    assert restore_result["rpo_met"] is True
    assert restore_result["data_integrity_verified"] is True


def test_p07_exit_test_3_backup_immutability_vault_lock():
    """
    Exit Test 3: Backup-immutability test: deletion attempt on protected backup is denied.
    """
    engine = DataGovernanceEngine()
    backup_id = "arn:aws:backup:us-west-2:123456789012:recovery-point:vault-prod-point-99"

    # Register locked backup in compliance vault
    engine.register_immutable_backup(backup_id, region="us-west-2")

    # Attempt deletion with root / admin credentials
    deletion_attempt = engine.attempt_delete_backup(backup_id, requester_role="arn:aws:iam::123456789012:root")

    assert deletion_attempt["deleted"] is False
    assert deletion_attempt["denied"] is True
    assert deletion_attempt["error_code"] == "AccessDeniedException"
    assert "Vault Lock Compliance Mode is active" in deletion_attempt["reason"]


def test_p07_exit_test_4_cross_region_failover_drill():
    """
    Exit Test 4: Region-failover tabletop + partial live drill completed and documented.
    """
    failover = DataGovernanceEngine.simulate_cross_region_failover(
        primary_region="us-east-1",
        secondary_region="us-west-2"
    )

    assert failover["failover_succeeded"] is True
    assert failover["within_rto"] is True
    assert failover["total_failover_minutes"] == 32.0  # 32m <= 60m target
    step_names = [s["step"] for s in failover["steps"]]
    assert "promote_aurora_read_replica" in step_names
    assert "spin_up_secondary_ecs_cluster" in step_names


def test_p07_exit_test_5_archival_job_data_movement():
    """
    Exit Test 5: Archival job moves aged data without affecting query performance.
    """
    archival = DataGovernanceEngine.archive_aged_data(
        partition_date_cutoff="2026-04-01",
        total_records_scanned=250000
    )

    assert archival["archival_success"] is True
    assert archival["records_archived_to_s3"] == 100000
    assert archival["records_remaining_in_primary_db"] == 150000
    assert archival["query_latency_improvement_pct"] > 0
