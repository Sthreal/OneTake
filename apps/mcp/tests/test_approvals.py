import pytest

from onetake_mcp.approvals import ApprovalStore
from onetake_mcp.client import OneTakeApiError


def test_approval_is_one_time_and_target_bound() -> None:
    store = ApprovalStore(ttl_seconds=60)
    record = store.create(action='video', target='prj_1:vid_1', summary='生成视频')

    with pytest.raises(OneTakeApiError, match='不匹配'):
        store.consume(record.approval_id, action='video', target='prj_2:vid_2')

    consumed = store.consume(record.approval_id, action='video', target='prj_1:vid_1')
    assert consumed.approval_id == record.approval_id
    with pytest.raises(OneTakeApiError, match='不存在'):
        store.consume(record.approval_id, action='video', target='prj_1:vid_1')