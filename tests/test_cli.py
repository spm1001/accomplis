"""Tests for accomplis CLI commands."""

import json
import sys
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# --- Fixtures ---


def make_task(task_id="t1", content="Test task", assignee_id=None, project_id="p1",
              comment_count=0, created_at="2026-01-01T00:00:00Z", section_id=None):
    """Create a mock Task object matching the SDK's interface."""
    task = SimpleNamespace(
        id=task_id,
        content=content,
        assignee_id=assignee_id,
        project_id=project_id,
        comment_count=comment_count,
        created_at=created_at,
        section_id=section_id,
    )
    task.to_dict = lambda: {
        "id": task.id,
        "content": task.content,
        "assignee_id": task.assignee_id,
        "project_id": task.project_id,
        "comment_count": task.comment_count,
        "created_at": task.created_at,
        "section_id": task.section_id,
    }
    return task


def make_project(project_id="p1", name="Test", workspace_id=None):
    """Create a mock Project object matching the SDK's interface."""
    return SimpleNamespace(id=project_id, name=name, workspace_id=workspace_id)


def make_collaborator(cid, name, email=""):
    return SimpleNamespace(id=cid, name=name, email=email)


def make_comment(content="", attachment=None):
    comment = SimpleNamespace(content=content, attachment=attachment)
    comment.to_dict = lambda: {"content": comment.content, "attachment": comment.attachment}
    return comment


def paginated(*items):
    """Simulate the SDK's paginated iterator (yields batches)."""
    yield list(items)


# --- get_current_user ---


class TestGetCurrentUser:
    @patch("accomplis.token_store.get_token", return_value="test-token")
    def test_returns_user_dict(self, mock_token):
        # Inject via the client seam, not by patching httpx.get — a patch that
        # stops matching the implementation silently degrades into a real
        # network call (it did, when get_current_user moved to _build_client).
        import httpx

        from accomplis import common

        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "123",
                    "full_name": "Test User",
                    "email": "test@example.com",
                },
            )

        stub = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(common, "_build_client", return_value=stub):
            user = common.get_current_user()

        assert user["id"] == "123"
        assert user["full_name"] == "Test User"
        assert user["email"] == "test@example.com"
        assert len(requests) == 1
        assert str(requests[0].url) == "https://api.todoist.com/api/v1/user"
        assert requests[0].headers["Authorization"] == "Bearer test-token"

    @patch("accomplis.token_store.get_token", return_value="bad-token")
    @patch("httpx.get")
    def test_raises_on_401(self, mock_get, mock_token):
        from accomplis.common import get_current_user
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            get_current_user()


# --- cmd_whoami ---


class TestWhoami:
    @patch("accomplis.cli.get_current_user")
    def test_human_output(self, mock_user, capsys):
        from accomplis.cli import cmd_whoami

        mock_user.return_value = {
            "id": "123",
            "full_name": "Sameer Modha",
            "email": "sameer@example.com",
        }

        args = SimpleNamespace(json=False)
        cmd_whoami(args)

        out = capsys.readouterr().out
        assert "Sameer Modha" in out
        assert "sameer@example.com" in out
        assert "123" in out

    @patch("accomplis.cli.get_current_user")
    def test_json_output(self, mock_user, capsys):
        from accomplis.cli import cmd_whoami

        mock_user.return_value = {
            "id": "123",
            "full_name": "Sameer Modha",
            "email": "sameer@example.com",
        }

        args = SimpleNamespace(json=True)
        cmd_whoami(args)

        out = json.loads(capsys.readouterr().out)
        assert out["id"] == "123"
        assert out["full_name"] == "Sameer Modha"


# --- Assignee enrichment ---


class TestAssigneeEnrichment:
    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    def test_assignee_name_resolved_in_task_output(self, mock_collect, mock_api, capsys):
        from accomplis.cli import cmd_get_task

        task = make_task(assignee_id="456", project_id="p1")
        collabs = [make_collaborator("456", "Lauren Thomas")]

        def side_effect(iterator):
            # Return different values based on what's being paginated
            return list(iterator)

        mock_api_instance = MagicMock()
        mock_api.return_value = mock_api_instance
        mock_api_instance.get_task.return_value = task

        # First call: get_collaborators, Second call: get_comments
        mock_collect.side_effect = [
            collabs,    # collaborators
            [],         # comments
        ]

        args = SimpleNamespace(id="t1")
        cmd_get_task(args)

        out = json.loads(capsys.readouterr().out)
        assert out["assignee_name"] == "Lauren Thomas"

    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    def test_null_assignee_gives_null_name(self, mock_collect, mock_api, capsys):
        from accomplis.cli import cmd_get_task

        task = make_task(assignee_id=None, project_id="p1")

        mock_api_instance = MagicMock()
        mock_api.return_value = mock_api_instance
        mock_api_instance.get_task.return_value = task

        mock_collect.side_effect = [
            [],  # comments (no collaborator call since assignee_id is None)
        ]

        args = SimpleNamespace(id="t1")
        cmd_get_task(args)

        out = json.loads(capsys.readouterr().out)
        assert out["assignee_name"] is None


# --- Auto-filter on workspace vs personal projects ---


class TestAutoFilter:
    """Workspace projects filter to assigned-to-me; personal projects show all."""

    @patch("accomplis.cli.get_current_user")
    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    @patch("accomplis.cli.resolve_project_object")
    def test_workspace_project_filters_to_assigned_only(self, mock_resolve, mock_collect,
                                                         mock_api, mock_user, capsys):
        """Workspace project default: only tasks assigned to me (no unassigned)."""
        from accomplis.cli import cmd_get_tasks

        mock_resolve.return_value = make_project("p1", "MIT Board", workspace_id="ws1")
        mock_user.return_value = {"id": "100", "full_name": "Me"}
        mock_api.return_value = MagicMock()

        my_task = make_task("t1", "My task", assignee_id="100")
        their_task = make_task("t2", "Their task", assignee_id="200")
        unassigned = make_task("t3", "Unassigned task", assignee_id=None)
        collabs = [
            make_collaborator("100", "Me"),
            make_collaborator("200", "Them"),
        ]

        mock_collect.side_effect = [
            [my_task, their_task, unassigned],  # get_tasks
            collabs,                             # get_collaborators
            [],                                  # comments for t1
        ]

        args = SimpleNamespace(
            project="MIT Board", project_id=None, section=None, section_id=None,
            label=None, assignee=None, team=False, unassigned=False,
            created_before=None, older_than=None, include_section_name=False,
        )
        cmd_get_tasks(args)

        out = json.loads(capsys.readouterr().out)
        contents = [t["content"] for t in out]
        assert "My task" in contents
        assert "Their task" not in contents
        assert "Unassigned task" not in contents

    @patch("accomplis.cli.get_current_user")
    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    @patch("accomplis.cli.resolve_project_object")
    def test_workspace_unassigned_flag_shows_untriaged(self, mock_resolve, mock_collect,
                                                        mock_api, mock_user, capsys):
        """--unassigned on workspace project shows only unassigned tasks."""
        from accomplis.cli import cmd_get_tasks

        mock_resolve.return_value = make_project("p1", "MIT Board", workspace_id="ws1")
        mock_user.return_value = {"id": "100", "full_name": "Me"}
        mock_api.return_value = MagicMock()

        my_task = make_task("t1", "My task", assignee_id="100")
        unassigned = make_task("t3", "Unassigned task", assignee_id=None)
        collabs = [make_collaborator("100", "Me")]

        mock_collect.side_effect = [
            [my_task, unassigned],  # get_tasks
            collabs,                # get_collaborators
            [],                     # comments for t3
        ]

        args = SimpleNamespace(
            project="MIT Board", project_id=None, section=None, section_id=None,
            label=None, assignee=None, team=False, unassigned=True,
            created_before=None, older_than=None, include_section_name=False,
        )
        cmd_get_tasks(args)

        out = json.loads(capsys.readouterr().out)
        contents = [t["content"] for t in out]
        assert "Unassigned task" in contents
        assert "My task" not in contents

    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    @patch("accomplis.cli.resolve_project_object")
    def test_team_flag_shows_all(self, mock_resolve, mock_collect, mock_api, capsys):
        """--team bypasses all filtering."""
        from accomplis.cli import cmd_get_tasks

        mock_resolve.return_value = make_project("p1", "MIT Board", workspace_id="ws1")
        mock_api.return_value = MagicMock()

        my_task = make_task("t1", "My task", assignee_id="100")
        their_task = make_task("t2", "Their task", assignee_id="200")
        collabs = [
            make_collaborator("100", "Me"),
            make_collaborator("200", "Them"),
        ]

        mock_collect.side_effect = [
            [my_task, their_task],  # get_tasks
            collabs,                # get_collaborators
            [],                     # comments for t1
            [],                     # comments for t2
        ]

        args = SimpleNamespace(
            project="MIT Board", project_id=None, section=None, section_id=None,
            label=None, assignee=None, team=True, unassigned=False,
            created_before=None, older_than=None, include_section_name=False,
        )
        cmd_get_tasks(args)

        out = json.loads(capsys.readouterr().out)
        assert len(out) == 2

    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    @patch("accomplis.cli.resolve_project_object")
    def test_personal_project_no_filter(self, mock_resolve, mock_collect, mock_api, capsys):
        """Personal project (no workspace_id): show all tasks, no filtering."""
        from accomplis.cli import cmd_get_tasks

        mock_resolve.return_value = make_project("p1", "Personal", workspace_id=None)
        mock_api.return_value = MagicMock()

        tasks = [make_task("t1", "Task A"), make_task("t2", "Task B")]

        mock_collect.side_effect = [
            tasks,  # get_tasks
            [],     # get_collaborators (empty)
            [],     # comments for t1
            [],     # comments for t2
        ]

        args = SimpleNamespace(
            project="Personal", project_id=None, section=None, section_id=None,
            label=None, assignee=None, team=False, unassigned=False,
            created_before=None, older_than=None, include_section_name=False,
        )
        cmd_get_tasks(args)

        out = json.loads(capsys.readouterr().out)
        assert len(out) == 2

    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    @patch("accomplis.cli.resolve_project_object")
    def test_personal_with_collaborators_no_filter(self, mock_resolve, mock_collect, mock_api, capsys):
        """Personal project WITH collaborators but no workspace_id: show all tasks."""
        from accomplis.cli import cmd_get_tasks

        mock_resolve.return_value = make_project("p1", "At Work", workspace_id=None)
        mock_api.return_value = MagicMock()

        my_task = make_task("t1", "My task", assignee_id="100")
        their_task = make_task("t2", "Shared task", assignee_id="200")
        unassigned = make_task("t3", "Unassigned", assignee_id=None)
        collabs = [
            make_collaborator("100", "Me"),
            make_collaborator("200", "Them"),
        ]

        mock_collect.side_effect = [
            [my_task, their_task, unassigned],  # get_tasks
            collabs,                             # get_collaborators
            [],                                  # comments for t1
            [],                                  # comments for t2
            [],                                  # comments for t3
        ]

        args = SimpleNamespace(
            project="At Work", project_id=None, section=None, section_id=None,
            label=None, assignee=None, team=False, unassigned=False,
            created_before=None, older_than=None, include_section_name=False,
        )
        cmd_get_tasks(args)

        out = json.loads(capsys.readouterr().out)
        assert len(out) == 3  # All tasks shown, no filtering


# --- Comment guard removal ---


class TestCommentGuardRemoval:
    @patch("accomplis.cli.get_api")
    @patch("accomplis.cli.collect_paginated")
    def test_comments_fetched_even_with_zero_comment_count(self, mock_collect, mock_api, capsys):
        from accomplis.cli import cmd_get_task

        task = make_task(comment_count=0)
        attachment_comment = make_comment(
            content="",
            attachment={"file_name": "report.pdf", "file_type": "application/pdf"},
        )

        mock_api_instance = MagicMock()
        mock_api.return_value = mock_api_instance
        mock_api_instance.get_task.return_value = task

        mock_collect.side_effect = [
            [attachment_comment],  # comments fetched despite count=0
        ]

        args = SimpleNamespace(id="t1")
        cmd_get_task(args)

        out = json.loads(capsys.readouterr().out)
        assert len(out["comments"]) == 1
        assert out["comments"][0]["attachment"]["file_name"] == "report.pdf"


# --- update: --no-section, --order; reorder ---


def make_update_args(**overrides):
    """Args namespace for cmd_update_task with all flags defaulted off."""
    defaults = dict(
        id="t1", content=None, description=None, project_id=None, project=None,
        section_id=None, section=None, no_section=False, order=None,
        labels=None, priority=None, due=None, assignee=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestNoSection:
    @patch("accomplis.cli.get_api")
    def test_no_section_moves_to_project_root(self, mock_api, capsys):
        """--no-section alone: move_task targets the task's own project."""
        from accomplis.cli import cmd_update_task

        task = make_task("t1", "In a section", project_id="p1", section_id="s1")
        api = MagicMock()
        mock_api.return_value = api
        api.get_task.return_value = task

        cmd_update_task(make_update_args(no_section=True))

        api.move_task.assert_called_once_with("t1", project_id="p1")
        api.update_task.assert_not_called()

    @patch("accomplis.cli.get_api")
    def test_no_section_conflicts_with_section(self, mock_api, capsys):
        from accomplis.cli import cmd_update_task

        with pytest.raises(SystemExit):
            cmd_update_task(make_update_args(no_section=True, section="Now"))
        assert "--no-section" in capsys.readouterr().err


class TestOrder:
    @patch("accomplis.cli.get_api")
    def test_order_passed_to_update(self, mock_api, capsys):
        from accomplis.cli import cmd_update_task

        task = make_task("t1", "Queue item", project_id="p1")
        api = MagicMock()
        mock_api.return_value = api
        api.get_task.return_value = task

        cmd_update_task(make_update_args(order=3))

        api.update_task.assert_called_once_with("t1", order=3)
        api.move_task.assert_not_called()


class TestReorder:
    @patch("accomplis.cli.api_call_with_retry", side_effect=lambda f, *a, **k: f(*a, **k))
    @patch("accomplis.cli.get_api")
    def test_reorder_assigns_sequential_positions(self, mock_api, mock_retry, capsys):
        from accomplis.cli import cmd_reorder

        api = MagicMock()
        mock_api.return_value = api

        cmd_reorder(SimpleNamespace(ids=["a", "b", "c"]))

        assert api.update_task.call_args_list == [
            (("a",), {"order": 1}),
            (("b",), {"order": 2}),
            (("c",), {"order": 3}),
        ]
        out = json.loads(capsys.readouterr().out)
        assert out["success"] is True
        assert [r["order"] for r in out["reordered"]] == [1, 2, 3]


class TestResolveAssignee:
    """tgt-husule: the ids that `collaborators` emits must round-trip into --assignee."""

    def _api(self):
        api = MagicMock()
        api.get_collaborators.return_value = paginated(
            make_collaborator("55347230", "Alex Chen", "alex@example.com"),
            make_collaborator("99881122", "Alexandra Smith", "asmith@example.com"),
        )
        return api

    def test_numeric_id_round_trips(self):
        from accomplis.common import resolve_assignee
        assert resolve_assignee(self._api(), "p1", "55347230") == "55347230"

    def test_email_resolves(self):
        from accomplis.common import resolve_assignee
        assert resolve_assignee(self._api(), "p1", "alex@example.com") == "55347230"

    def test_exact_name_resolves(self):
        from accomplis.common import resolve_assignee
        assert resolve_assignee(self._api(), "p1", "Alex Chen") == "55347230"

    def test_unique_substring_resolves(self):
        from accomplis.common import resolve_assignee
        assert resolve_assignee(self._api(), "p1", "Alexandra") == "99881122"

    def test_ambiguous_substring_errors_naming_candidates(self, capsys):
        from accomplis.common import resolve_assignee
        with pytest.raises(SystemExit):
            resolve_assignee(self._api(), "p1", "Alex")
        err = capsys.readouterr().err
        assert "matches several" in err
        assert "Alex Chen" in err and "Alexandra Smith" in err

    def test_not_found_names_accepted_forms_and_available(self, capsys):
        from accomplis.common import resolve_assignee
        with pytest.raises(SystemExit):
            resolve_assignee(self._api(), "p1", "Nobody")
        err = capsys.readouterr().err
        assert "name, email, or id" in err
        assert "Alex Chen" in err


class TestDoneNote:
    @patch("accomplis.cli.get_api")
    def test_note_appends_to_description_then_completes(self, mock_api, capsys):
        from accomplis.cli import cmd_complete_task

        task = make_task("t1", "Thing")
        task.description = "Existing context"
        api = MagicMock()
        mock_api.return_value = api
        api.get_task.return_value = task
        api.complete_task.return_value = True

        cmd_complete_task(SimpleNamespace(id="t1", note="Closed: shipped in 1.29"))

        api.update_task.assert_called_once_with(
            "t1", description="Existing context\n\nClosed: shipped in 1.29"
        )
        api.complete_task.assert_called_once_with("t1")
        out = json.loads(capsys.readouterr().out)
        assert out["success"] is True

    @patch("accomplis.cli.get_api")
    def test_note_on_empty_description_stands_alone(self, mock_api, capsys):
        from accomplis.cli import cmd_complete_task

        task = make_task("t1", "Thing")
        task.description = ""
        api = MagicMock()
        mock_api.return_value = api
        api.get_task.return_value = task
        api.complete_task.return_value = True

        cmd_complete_task(SimpleNamespace(id="t1", note="Done note"))

        api.update_task.assert_called_once_with("t1", description="Done note")

    @patch("accomplis.cli.get_api")
    def test_no_note_skips_description_update(self, mock_api, capsys):
        from accomplis.cli import cmd_complete_task

        api = MagicMock()
        mock_api.return_value = api
        api.complete_task.return_value = True

        cmd_complete_task(SimpleNamespace(id="t1", note=None))

        api.update_task.assert_not_called()
        api.get_task.assert_not_called()
