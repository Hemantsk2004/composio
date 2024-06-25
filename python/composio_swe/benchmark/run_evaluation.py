# pylint: disable=logging-fstring-interpolation
import datetime
import logging

from datasets import load_dataset
from rich.logging import RichHandler

from composio import Action, Composio
from composio.local_tools.local_workspace.workspace.actions.create_workspace import (
    CreateWorkspaceResponse,
)
from python.composio_swe.composio_swe.agent.swe import CoderAgent, CoderAgentArgs
from python.composio_swe.composio_swe.config.constants import KEY_API_KEY
from python.composio_swe.composio_swe.config.context import Context, set_context


# get logger
LOGGER_NAME = "local_workspace"

handler = RichHandler(show_time=False, show_path=False)
handler.setLevel(logging.DEBUG)
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.propagate = False


# princeton swe bench lite dataset has these fields
# instance_id: (str) - A formatted instance identifier, usually as repo_owner__repo_name-PR-number.
# patch: (str) - The gold patch, the patch generated by the PR (minus test-related code), that resolved the issue.
# repo: (str) - The repository owner/name identifier from GitHub.
# base_commit: (str) - The commit hash of the repository representing the HEAD of the repository before the solution PR is applied.
# hints_text: (str) - Comments made on the issue prior to the creation of the solution PR’s first commit creation date.
# created_at: (str) - The creation date of the pull request.
# test_patch: (str) - A test-file patch that was contributed by the solution PR.
# problem_statement: (str) - The issue title and body.
# version: (str) - Installation version to use for running evaluation.
# environment_setup_commit: (str) - commit hash to use for environment setup and installation.
# FAIL_TO_PASS: (str) - A json list of strings that represent the set of tests resolved by the PR and tied to the issue resolution.
# PASS_TO_PASS: (str) - A json list of strings that represent tests that should pass before and after the PR application.


def filter_from_repo_name(curr_dataset, repo_name):
    filtered_dataset = curr_dataset.filter(
        lambda x: x["repo"] == repo_name.strip().lower()
    )
    return filtered_dataset


def get_issues_dataset():
    test_dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test[1:50]")
    return test_dataset


def build_issue_description(hints, problem_statement):
    if not problem_statement or not problem_statement.strip():
        raise ValueError("problem statement is empty")
    tmpl = ""
    tmpl += f"""Here is the issue, that you have to solve all on your own:\n{problem_statement}"""
    if hints:
        tmpl += f"""\n\nHere are few hints to solve the issue described in problem_statement: \n{hints}"""

    return tmpl


def run():
    """
    Main function to load and display entries from the SWE-bench lite dataset.
    """

    issues = get_issues_dataset()

    composio_client = Composio()
    repo_to_workspace_map = {}
    for count, issue in enumerate(issues, 1):
        try:
            repo = issue["repo"]
            print(f"Processing {count}th issue with repoMap: {repo_to_workspace_map}")
            print(f"Repo: {repo}")
            print(f"Issue description: {issue['hints_text']}")
            if repo not in repo_to_workspace_map:
                start_time = datetime.datetime.now()
                workspace_create_resp = CreateWorkspaceResponse.model_validate(
                    composio_client.actions.execute(
                        action=Action.LOCALWORKSPACE_CREATEWORKSPACEACTION, params={}
                    )
                )
                workspace_id = workspace_create_resp.workspace_id
                workspace_creation_time = datetime.datetime.now() - start_time
                print(
                    "workspace is created, workspace-id is: %s, creation time: %s",
                    workspace_id,
                    workspace_creation_time,
                )

                start_time = datetime.datetime.now()
                composio_client.actions.execute(
                    action=Action.CMDMANAGERTOOL_GITHUBCLONECMD,
                    params={
                        "workspace_id": workspace_id,
                        "repo_name": repo,
                    },
                )
                git_clone_time = datetime.datetime.now() - start_time
                print("git clone completed, time taken: %s", git_clone_time)
                repo_to_workspace_map[repo] = workspace_id
            else:
                print("Resetting repository to base commit")
                workspace_id = repo_to_workspace_map[repo]
                composio_client.actions.execute(
                    action=Action.CMDMANAGERTOOL_GITHUBCLONECMD,
                    params={
                        "workspace_id": workspace_id,
                        "repo_name": repo,
                        "just_reset": True,
                    },
                )

            issue_description = build_issue_description(
                issue["hints_text"], issue["problem_statement"]
            )
            print(f"Issue description: {issue_description}")
            patch = issue["patch"]
            install_commit_id = issue["environment_setup_commit"]
            logger.info(
                "found patch-id: %s and install_commit_id: %s", patch, install_commit_id
            )
            issue_config = {
                "repo_name": issue["repo"],
                "issue_id": issue["instance_id"],
                "base_commit_id": issue["base_commit"],
                "issue_desc": issue_description,
            }
            logger.info(
                f"starting agent for issue-id: {issue['instance_id']}\n"
                f"issue-description: {issue_description}\n"
                f"repo_name: {issue['repo']}\n"
            )

            print("--------------------------------------------------")

            model_env_config = {
                KEY_API_KEY: "test-key",
                "azure_endpoint": "test-endpoint",
                "model_env": "azure",
            }
            ctx = Context()
            ctx.issue_config = issue_config
            ctx.model_env = model_env_config
            set_context(ctx)

            args = CoderAgentArgs(agent_logs_dir=ctx.agent_logs_dir)
            coder = CoderAgent(args)
            coder.run(
                issue_config=ctx.issue_config, workspace_id=repo_to_workspace_map[repo]
            )
        except Exception as e:
            print(f"Error processing issue {issue['instance_id']}: {e}")


if __name__ == "__main__":
    run()