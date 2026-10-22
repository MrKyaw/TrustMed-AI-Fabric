from trustmed_fabric.models import Asset, AssetStatus, ContentSection


def _make_asset(asset_id: str = "ONC-HCP-DA-001") -> Asset:
    return Asset(
        id=asset_id,
        title="Title",
        brand="ONCRAVIA",
        therapeutic_area="oncology",
        asset_type="DETAIL_AID",
        channel="WEB",
        market="US",
        audience="HCP",
        status=AssetStatus.DRAFT,
        version=1,
        summary="This is a valid summary for an asset.",
        sections=[ContentSection(id="intro", heading="Heading", body="This is a valid body for an approved asset.")],
        tags=["therapeutic_area:oncology"],
        owner="Owner",
        source_system="content-studio",
        created_at=__import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").UTC),
        updated_at=__import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").UTC),
    )


def test_store_roundtrip_and_counts(store) -> None:
    asset = _make_asset()
    store.put("asset", asset)
    assert store.count("asset") == 1
    assert store.get_model("asset", "ONC-HCP-DA-001", Asset) == asset
    assert store.list_models("asset", Asset)[0].id == asset.id


def test_store_ledger_verification_and_event(store) -> None:
    event = store.append_event(
        event_type="asset.created",
        subject_type="asset",
        subject_id="ONC-HCP-DA-001",
        actor="owner",
        payload={"title": "Title"},
    )
    assert event.sequence == 1
    verification = store.verify_ledger()
    assert verification["valid"] is True
    assert verification["events"] == 1
    assert verification["head"] == event.hash
    assert store.events(limit=10)[0].id == event.id


def test_store_append_event_is_hash_chained(store) -> None:
    first = store.append_event(event_type="a", subject_type="asset", subject_id="1", actor="x")
    second = store.append_event(event_type="b", subject_type="asset", subject_id="2", actor="y")
    assert second.prev_hash == first.hash


def test_store_idempotency_and_ai_trace(store) -> None:
    store.put_idempotent("key", "op", {"ok": True}, 201)
    replay = store.get_idempotent("key")
    assert replay is not None
    assert replay["operation"] == "op"
    assert replay["response"] == {"ok": True}
    store.save_ai_trace(
        trace_id="trc_1",
        question="question",
        market="US",
        audience="HCP",
        channel=None,
        refused=False,
        answer="answer",
        citations=[],
        checks=[],
        latency_ms=1.2,
        model="model",
    )
    trace = store.get_ai_trace("trc_1")
    assert trace is not None
    assert trace["refused"] is False


def test_store_reset(store) -> None:
    store.append_event(event_type="a", subject_type="asset", subject_id="1", actor="x")
    store.reset()
    assert store.event_count() == 0
    assert store.count() == 0
