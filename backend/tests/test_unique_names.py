"""Generic resource names must not repeat between plans (S3 names are global)."""
import json, os, re
from types import SimpleNamespace as NS
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.llm.client import llm_client
from app.naming import make_names_unique, plan_suffix
from app.schemas.cloud import CloudPlan, CloudResource


def _ir(*resources):
    return NS(cloud=CloudPlan(provider="aws", region="us-east-1", environment="dev", resources=list(resources)), assumptions=[])


def _bucket(name="app_bucket", bucket_name=None, **extra):
    props = {"bucket_name": bucket_name} if bucket_name else {}
    props.update(extra)
    return CloudResource(type="object_storage", name=name, properties=props)


def test_suffix_comes_from_plan_id():
    assert plan_suffix("plan_dbeed1f3") == "dbeed1"


def test_generic_bucket_gets_suffix():
    ir = _ir(_bucket(bucket_name="app-data-bucket"))
    ch = make_names_unique(ir, "create an s3 bucket", "plan_dbeed1f3")
    assert ir.cloud.resources[0].properties["bucket_name"] == "app-data-bucket-dbeed1"
    assert ch and ch[0]["old"] == "app-data-bucket"
    assert any("Names made unique" in a for a in ir.assumptions)


def test_two_plans_never_share_a_bucket_name():
    a, b = _ir(_bucket(bucket_name="app-data-bucket")), _ir(_bucket(bucket_name="app-data-bucket"))
    make_names_unique(a, "create an s3 bucket", "plan_11111111")
    make_names_unique(b, "create an s3 bucket", "plan_22222222")
    assert a.cloud.resources[0].properties["bucket_name"] != b.cloud.resources[0].properties["bucket_name"]


def test_name_typed_by_user_is_kept_exactly():
    ir = _ir(_bucket(bucket_name="my-logs-123"))
    assert make_names_unique(ir, "create an s3 bucket named my-logs-123", "plan_dbeed1f3") == []
    assert ir.cloud.resources[0].properties["bucket_name"] == "my-logs-123"


def test_name_typed_in_requirements_md_is_kept():
    ir = _ir(_bucket(bucket_name="team-assets"))
    assert make_names_unique(ir, "add versioning\n- s3_bucket: name=team-assets", "plan_dbeed1f3") == []


def test_similar_prefix_in_prompt_does_not_count_as_stated():
    ir = _ir(_bucket(bucket_name="my-logs"))
    assert make_names_unique(ir, "create bucket my-logs-123", "plan_dbeed1f3")


def test_name_taken_from_logical_name_when_property_missing():
    ir = _ir(_bucket(name="site_bucket"))
    make_names_unique(ir, "create a bucket", "plan_dbeed1f3")
    assert ir.cloud.resources[0].properties["bucket_name"] == "site-bucket-dbeed1"


def test_no_double_suffix_on_revised_plan():
    ir = _ir(_bucket(bucket_name="app-data-bucket-dbeed1"))
    assert make_names_unique(ir, "add versioning", "plan_99999999") == []


def test_dependents_and_labels_untouched():
    ver = CloudResource(type="bucket_versioning", name="ver", properties={"bucket_name": "app_bucket"})
    ir = _ir(_bucket(name="app_bucket", bucket_name="app-data-bucket"), ver)
    make_names_unique(ir, "create a bucket", "plan_dbeed1f3")
    assert ir.cloud.resources[0].name == "app_bucket"                       # terraform label unchanged
    assert ir.cloud.resources[1].properties["bucket_name"] == "app_bucket"  # reference unchanged


def test_long_names_stay_within_aws_limits():
    ir = _ir(_bucket(bucket_name="a" * 80))
    make_names_unique(ir, "x", "plan_dbeed1f3")
    n = ir.cloud.resources[0].properties["bucket_name"]
    assert len(n) <= 63 and re.fullmatch(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]", n)


def test_other_account_level_names():
    rds = CloudResource(type="managed_database", name="main_db", properties={})
    sqs = CloudResource(type="queue", name="jobs", properties={})
    role = CloudResource(type="iam_role", name="app_role", properties={})
    ir = _ir(rds, sqs, role)
    make_names_unique(ir, "create db queue role", "plan_dbeed1f3")
    r, q, i = (x.properties for x in ir.cloud.resources)
    assert r["identifier"] == "main-db-dbeed1" and r["identifier"][0].isalpha()
    assert q["queue_name"].endswith("-dbeed1") and i["role_name"].endswith("-dbeed1")


def test_unrelated_resources_untouched():
    vpc = CloudResource(type="virtual_network", name="main_vpc", properties={"cidr_block": "10.0.0.0/16"})
    ir = _ir(vpc)
    assert make_names_unique(ir, "create a vpc", "plan_dbeed1f3") == []
    assert ir.cloud.resources[0].properties == {"cidr_block": "10.0.0.0/16"}


def test_end_to_end_two_requests_get_different_bucket_names_in_terraform(monkeypatch):
    """Offline fallback planner used to hardcode 'app-data-bucket' for every request."""
    monkeypatch.setattr(llm_client, "is_healthy", lambda: False)
    client = TestClient(app)
    names, plan_ids = [], []
    for _ in range(2):
        sid = client.post("/api/sessions", json={}).json()
        sid = sid.get("id") or sid.get("session_id")
        r = client.post("/api/chat", json={"prompt": "create an s3 bucket", "session_id": sid, "environment": "dev"})
        assert r.status_code == 200, r.text
        m = re.search(r'"plan_id":\s*"(plan_[0-9a-f]+)"', json.dumps(r.json()))
        assert m, r.text[:300]
        plan_ids.append(m.group(1))
        tf = open(os.path.join(settings.TERRAFORM_WORKSPACE, m.group(1), "main.tf")).read()
        found = re.findall(r'bucket\s*=\s*"([^"]+)"', tf)
        assert found, tf[:300]
        names.append(found[0])
    assert plan_ids[0] != plan_ids[1]
    assert names[0] != names[1], names
    assert all(n.startswith("app-data-bucket-") for n in names), names
