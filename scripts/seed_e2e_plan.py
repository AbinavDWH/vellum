import json
import sys
from app.database import SessionLocal
from app.models import PlanRecord, ExecutionRecord
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.engines.terraform_generator import tf_generator

plan_id = sys.argv[1] if len(sys.argv) > 1 else "e2e_seeded_plan"

db = SessionLocal()
db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).delete()
db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).delete()
db.commit()

ir = UniversalIR(
    intent="deploy_cloud",
    cloud=CloudPlan(
        provider="aws",
        region="us-east-1",
        environment="local",
        resources=[
            CloudResource(
                type="object_storage",
                name="e2e-seed-bucket",
                properties={"bucket_name": "e2e-seed-bucket"},
            )
        ],
    ),
)
pdir = tf_generator.generate(ir, environment="local", plan_id=plan_id)
with open(f"{pdir}/main.tf") as f:
    tf = f.read()

rec = PlanRecord(
    plan_id=plan_id,
    prompt="Seed bucket for E2E testing",
    intent="deploy_cloud",
    risk_level="low",
    status="approved",
    ir_json=json.dumps(ir.model_dump()),
    terraform_code=tf,
    requires_confirmation_text=False,
)
db.add(rec)
db.commit()
db.close()
print(f"SUCCESS_SEEDED:{plan_id}")
