from narrative_state_engine.graph_view import build_branch_graph, build_state_graph, build_transition_graph


def test_state_graph_returns_react_flow_nodes_and_edges():
    graph = build_state_graph(
        [
            {
                "object_id": "task:story:state:character:char-a",
                "object_type": "character",
                "object_key": "char-a",
                "display_name": "A",
                "authority": "author_confirmed",
                "confidence": 0.9,
                "status": "confirmed",
                "payload": {"character_id": "char-a", "related_character_ids": ["char-b"]},
            },
            {
                "object_id": "task:story:state:character:char-b",
                "object_type": "character",
                "object_key": "char-b",
                "display_name": "B",
                "authority": "canonical",
                "confidence": 0.8,
                "status": "confirmed",
                "payload": {"character_id": "char-b"},
            },
        ]
    )

    payload = graph.model_dump(mode="json")
    assert payload["nodes"][0]["data"]["object_id"] == "task:story:state:character:char-a"
    assert payload["nodes"][0]["data"]["authority"] == "author_confirmed"
    assert payload["edges"][0]["source"] == "task:story:state:character:char-a"
    assert payload["edges"][0]["target"] == "task:story:state:character:char-b"


def test_branch_and_transition_graphs_project_backend_rows():
    branch_graph = build_branch_graph(
        [
            {"branch_id": "b1", "status": "draft", "base_state_version_no": 1},
            {"branch_id": "b2", "parent_branch_id": "b1", "status": "accepted", "base_state_version_no": 1},
        ]
    )
    transition_graph = build_transition_graph(
        [
            {
                "transition_id": "tr-1",
                "target_object_id": "obj-1",
                "target_object_type": "character",
                "transition_type": "candidate_accept",
                "field_path": "name",
            }
        ]
    )

    assert branch_graph.edges[0].source == "b1"
    assert transition_graph.edges[0].target == "obj-1"


def test_transition_graph_exposes_action_id():
    graph = build_transition_graph(
        [
            {
                "transition_id": "tr-action",
                "target_object_id": "obj-action",
                "target_object_type": "character",
                "transition_type": "lock_state_field",
                "field_path": "summary",
                "action_id": "review-action-123",
                "status": "accepted",
                "created_at": "2026-05-10T00:00:00Z",
            }
        ]
    )

    payload = graph.model_dump(mode="json")
    transition_node = next(node for node in payload["nodes"] if node["id"] == "tr-action")
    assert transition_node["data"]["action_id"] == "review-action-123"
    assert transition_node["data"]["created_at"] == "2026-05-10T00:00:00Z"
    assert payload["edges"][0]["data"]["action_id"] == "review-action-123"
    assert payload["metadata"]["has_action_links"] is True
