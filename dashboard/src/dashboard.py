"""The main module of the QA Dashboard."""
import json
import time
import datetime
import os
import sys
import requests
import csv
import shutil
import re

from coreapi import *
from jobsapi import *
from configuration import *
from results import *
from html_generator import *
from perf_tests import *
from smoke_tests import *
from sla import *
from ci_jobs import *
from cliargs import *
from config import *
from repositories import *
from progress_bar import *
from source_files import *
from unit_tests import *


def check_environment_variable(env_var_name):
    """Check if the given environment variable exists."""
    print("Checking: {e} environment variable existence".format(
        e=env_var_name))
    if env_var_name not in os.environ:
        print("Fatal: {e} environment variable has to be specified"
              .format(e=env_var_name))
        sys.exit(1)
    else:
        print("    ok")


def check_environment_variables():
    """Check if all required environment variables exist."""
    environment_variables = [
        "F8A_API_URL_STAGE",
        "F8A_API_URL_PROD",
        "F8A_JOB_API_URL_STAGE",
        "F8A_JOB_API_URL_PROD",
        "RECOMMENDER_API_TOKEN_STAGE",
        "RECOMMENDER_API_TOKEN_PROD",
        "JOB_API_TOKEN_STAGE",
        "JOB_API_TOKEN_PROD",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_REGION_NAME"]
    for environment_variable in environment_variables:
        check_environment_variable(environment_variable)


def check_system(core_api, jobs_api):
    """Check if all system endpoints are available and that tokens are valid."""
    # try to access system endpoints
    print("Checking: core API and JOBS API endpoints")
    core_api_available = core_api.is_api_running()
    jobs_api_available = jobs_api.is_api_running()

    if core_api_available and jobs_api_available:
        print("    ok")
    else:
        print("    Fatal: tested system is not available")

    # check the authorization token for the core API
    print("Checking: authorization token for the core API")
    core_api_auth_token = core_api.check_auth_token_validity()

    if core_api_auth_token:
        print("    ok")
    else:
        print("    error")

    # check the authorization token for the jobs API
    print("Checking: authorization token for the jobs API")
    jobs_api_auth_token = jobs_api.check_auth_token_validity()

    if jobs_api_auth_token:
        print("    ok")
    else:
        print("    error")

    return {"core_api_available": core_api_available,
            "jobs_api_available": jobs_api_available,
            "core_api_auth_token": core_api_auth_token,
            "jobs_api_auth_token": jobs_api_auth_token}


# files that are to be ignored by Pylint
ignored_files_for_pylint = {
}

# files that are to be ignored by Pydocchecker
ignored_files_for_pydocstyle = {
    "fabric8-analytics-worker": ["tests/data/license/license.py"]
}

ci_job_types = [
    "test_job",
    "build_job",
    "pylint_job",
    "pydoc_job"
]

teams = [
    "core",
    "integration"
]

JENKINS_URL = "https://ci.centos.org"
JOBS_STATUSES_FILENAME = "jobs.json"


def is_repository_cloned(repository):
    """Check if the directory with cloned repository exist."""
    return os.path.isdir(repository)


def clone_repository(repository):
    """Clone the selected repository."""
    print("Cloning the repository {repository}".format(repository=repository))
    prefix = "https://github.com/"
    command = "git clone --single-branch --depth 1 {prefix}/{repo}.git".format(prefix=prefix,
                                                                               repo=repository)
    os.system(command)


def fetch_repository(repository):
    """Fetch the selected repository."""
    print("Fetching changes from the repository {repository}".format(repository=repository))
    command = "pushd {repository}; git fetch; popd".format(repository=repository)
    os.system(command)


def clone_or_fetch_repository(repository):
    """Clone or fetch the selected repository."""
    if is_repository_cloned(repository):
        fetch_repository(repository)
    else:
        clone_repository(repository)


def run_pylint(repository):
    """Run Pylint checker against the selected repository."""
    command = "pushd {repo};./run-linter.sh > ../{repo}.linter.txt;popd".format(repo=repository)
    os.system(command)


def run_docstyle_check(repository):
    """Run PyDocsStyle checker against the selected repository."""
    command = "pushd {repo};./check-docstyle.sh > ../{repo}.pydocstyle.txt;popd".format(
        repo=repository)
    os.system(command)


def percentage(part1, part2):
    """Compute percentage of failed tests."""
    total = part1 + part2
    if total == 0:
        return "0"
    perc = 100.0 * part2 / total
    return "{:.0f}".format(perc)


def parse_linter_results(filename):
    """Parse results generated by Python linter or by PyDocStyle."""
    source = None

    files = {}
    passed = 0
    failed = 0
    total = 0

    with open(filename) as fin:
        for line in fin:
            line = line.rstrip()
            if line.endswith(".py"):
                source = line.strip()
            if line.endswith("    Pass"):
                if source:
                    passed += 1
                    total += 1
                    files[source] = True
            if line.endswith("    Fail"):
                if source:
                    failed += 1
                    total += 1
                    files[source] = False

    return {"files": files,
            "total": total,
            "passed": passed,
            "failed": failed,
            "passed%": percentage(failed, passed),
            "failed%": percentage(passed, failed),
            "progress_bar_class": progress_bar_class(percentage(failed, passed)),
            "progress_bar_width": progress_bar_width(percentage(failed, passed))}


def parse_pylint_results(repository):
    """Parse results generated by Python linter."""
    return parse_linter_results(repository + ".linter.txt")


def parse_docstyle_results(repository):
    """Parse results generated by PyDocStyle."""
    return parse_linter_results(repository + ".pydocstyle.txt")


def update_overall_status(results, repository):
    """Update the overall status of all tested systems (stage, prod)."""
    remarks = ""

    source_files = results.source_files[repository]["count"]
    linter_checks = results.repo_linter_checks[repository]
    docstyle_checks = results.repo_docstyle_checks[repository]
    unit_test_coverage = results.unit_test_coverage[repository]

    linter_checks_total = linter_checks["total"]
    docstyle_checks_total = docstyle_checks["total"]

    ignored_pylint_files = len(ignored_files_for_pylint.get(repository, []))
    ignored_pydocstyle_files = len(ignored_files_for_pydocstyle.get(repository, []))

    status = source_files == (linter_checks_total + ignored_pylint_files) and \
        source_files == (docstyle_checks_total + ignored_pydocstyle_files) and \
        linter_checks["failed"] == 0 and docstyle_checks["failed"] == 0 and \
        unit_test_coverage_ok(unit_test_coverage)

    if source_files != linter_checks_total + ignored_pylint_files:
        remarks += "not all source files are checked by linter<br>"

    if source_files != docstyle_checks_total + ignored_pydocstyle_files:
        remarks += "not all source files are checked by pydocstyle<br>"

    if linter_checks_total + ignored_pylint_files != \
       docstyle_checks_total + ignored_pydocstyle_files:
        remarks += ", linter checked {n1} files, but pydocstyle checked {n2} files".format(
            n1=linter_checks_total, n2=docstyle_checks_total)

    if unit_test_coverage is not None:
        if not unit_test_coverage_ok(unit_test_coverage):
            remarks += "improve code coverage<br>"
    else:
        remarks += "unit tests has not been setup<br>"

    if linter_checks["failed"] != 0:
        remarks += "linter failed<br>"

    if docstyle_checks["failed"] != 0:
        remarks += "pydocstyle check failed<br>"

    if ignored_pylint_files:
        remarks += "{n} file{s} ignored by pylint<br>".format(
            n=ignored_pylint_files, s="s" if ignored_pylint_files > 1 else "")

    if ignored_pydocstyle_files:
        remarks += "{n} file{s} ignored by pydocstyle<br>".format(
            n=ignored_pydocstyle_files, s="s" if ignored_pydocstyle_files > 1 else "")

    results.overall_status[repository] = status
    results.remarks[repository] = remarks


def delete_work_files(repository):
    """Cleanup the CWD from the work files used to analyze given repository."""
    os.remove("{repo}.count".format(repo=repository))
    os.remove("{repo}.linter.txt".format(repo=repository))
    os.remove("{repo}.pydocstyle.txt".format(repo=repository))


def cleanup_repository(repository):
    """Cleanup the directory with the clone of specified repository."""
    # let's do very basic check that the repository is really local dir
    if '/' not in repository:
        print("cleanup " + repository)
        shutil.rmtree(repository, ignore_errors=True)


def export_into_csv(results):
    """Export the results into CSV file."""
    record = [
        datetime.date.today().strftime("%Y-%m-%d"),
        int(results.stage["core_api_available"]),
        int(results.stage["jobs_api_available"]),
        int(results.stage["core_api_auth_token"]),
        int(results.stage["jobs_api_auth_token"]),
        int(results.production["core_api_available"]),
        int(results.production["jobs_api_available"]),
        int(results.production["core_api_auth_token"]),
        int(results.production["jobs_api_auth_token"])
    ]

    for repository in repositories:
        record.append(results.source_files[repository]["count"])
        record.append(results.source_files[repository]["total_lines"])
        record.append(results.repo_linter_checks[repository]["total"])
        record.append(results.repo_linter_checks[repository]["passed"])
        record.append(results.repo_linter_checks[repository]["failed"])
        record.append(results.repo_docstyle_checks[repository]["total"])
        record.append(results.repo_docstyle_checks[repository]["passed"])
        record.append(results.repo_docstyle_checks[repository]["failed"])

    with open('dashboard.csv', 'a') as fout:
        writer = csv.writer(fout)
        writer.writerow(record)


def prepare_data_for_liveness_table(results, ci_jobs, job_statuses):
    """Prepare data for sevices liveness/readiness table on the dashboard."""
    cfg = Configuration()

    core_api = CoreApi(cfg.stage.core_api_url, cfg.stage.core_api_token)
    jobs_api = JobsApi(cfg.stage.jobs_api_url, cfg.stage.jobs_api_token)
    results.stage = check_system(core_api, jobs_api)

    core_api = CoreApi(cfg.prod.core_api_url, cfg.prod.core_api_token)
    jobs_api = JobsApi(cfg.prod.jobs_api_url, cfg.prod.jobs_api_token)
    results.production = check_system(core_api, jobs_api)

    smoke_tests = SmokeTests(ci_jobs, job_statuses)
    results.smoke_tests_results = smoke_tests.results
    results.smoke_tests_links = smoke_tests.ci_jobs_links
    results.smoke_tests_statuses = smoke_tests.ci_jobs_statuses


def prepare_data_for_sla_table(results):
    """Prepare data for SLA table on the dashboard."""
    perf_tests = PerfTests()
    perf_tests.read_results()
    perf_tests.compute_statistic()
    results.perf_tests_results = perf_tests.results
    results.perf_tests_statistic = perf_tests.statistic

    results.sla_thresholds = SLA


def prepare_data_for_repositories(repositories, results, ci_jobs, job_statuses,
                                  clone_repositories_enabled, cleanup_repositories_enabled,
                                  code_quality_table_enabled, ci_jobs_table_enabled):
    """Perform clone/fetch repositories + run pylint + run docstyle script + accumulate results."""
    for repository in repositories:

        # clone or fetch the repository if the cloning/fetching is not disabled via CLI arguments
        if clone_repositories_enabled:
            clone_or_fetch_repository(repository)

        if code_quality_table_enabled:
            run_pylint(repository)
            run_docstyle_check(repository)

            results.source_files[repository] = get_source_files(repository)
            results.repo_linter_checks[repository] = parse_pylint_results(repository)
            results.repo_docstyle_checks[repository] = parse_docstyle_results(repository)

        # delete_work_files(repository)

        if cleanup_repositories_enabled:
            cleanup_repository(repository)

        if ci_jobs_table_enabled:
            for job_type in ci_job_types:
                url = ci_jobs.get_job_url(repository, job_type)
                name = ci_jobs.get_job_name(repository, job_type)
                job_status = job_statuses.get(name)
                results.ci_jobs_links[repository][job_type] = url
                results.ci_jobs_statuses[repository][job_type] = job_status
            results.unit_test_coverage[repository] = read_unit_test_coverage(ci_jobs, JENKINS_URL,
                                                                             repository)
        if code_quality_table_enabled:
            update_overall_status(results, repository)


def read_jobs_statuses(filename):
    """Deserialize statuses for all jobs from the JSON file."""
    with open(filename) as fin:
        return json.load(fin)["jobs"]


def store_jobs_statuses(filename, data):
    """Serialize statuses of all jobs into the JSON file."""
    with open(filename, "w") as fout:
        fout.write(data)


def jenkins_api_query_job_statuses(jenkins_url):
    """Construct API query to Jenkins (CI)."""
    return "{url}/api/json?tree=jobs[name,color]".format(url=jenkins_url)


def jenkins_api_query_build_statuses(jenkins_url):
    """Construct API query to Jenkins (CI)."""
    return "{url}/api/json?tree=builds[result]".format(url=jenkins_url)


def jobs_as_dict(raw_jobs):
    """Construct a dictionary with job name as key and job status as value."""
    return dict((job["name"], job["color"]) for job in raw_jobs if "color" in job)


def read_ci_jobs_statuses(jenkins_url):
    """Read statuses of all jobs from the Jenkins (CI)."""
    api_query = jenkins_api_query_job_statuses(jenkins_url)
    response = requests.get(api_query)
    raw_jobs = response.json()["jobs"]

    # for debugging purposes only
    # store_jobs_statuses(JOBS_STATUSES_FILENAME, response.text)

    # raw_jobs = read_jobs_statuses(JOBS_STATUSES_FILENAME)
    return jobs_as_dict(raw_jobs)


def read_job_statuses(ci_jobs, ci_jobs_table_enabled, liveness_table_enabled):
    """Read job statuses from the CI, but only if its necessary."""
    if ci_jobs_table_enabled or liveness_table_enabled:
        return read_ci_jobs_statuses(JENKINS_URL)
    else:
        return None


def production_smoketests_status(ci_jobs):
    """Read total number of remembered builds and succeeded builds as well."""
    job_url = ci_jobs.get_job_url("production", "smoketests")
    api_query = jenkins_api_query_build_statuses(job_url)
    response = requests.get(api_query)
    builds = response.json()["builds"]
    total_builds = [b for b in builds if b["result"] is not None]
    success_builds = [b for b in builds if b["result"] == "SUCCESS"]
    return len(total_builds), len(success_builds)


def main():
    """Entry point to the QA Dashboard."""
    config = Config()
    cli_arguments = cli_parser.parse_args()

    # some CLI arguments are used to DISABLE given feature of the dashboard,
    # but let's not use double negation everywhere :)
    ci_jobs_table_enabled = not cli_arguments.disable_ci_jobs
    code_quality_table_enabled = not cli_arguments.disable_code_quality
    liveness_table_enabled = not cli_arguments.disable_liveness
    sla_table_enabled = not cli_arguments.disable_sla
    clone_repositories_enabled = cli_arguments.clone_repositories
    cleanup_repositories_enabled = cli_arguments.cleanup_repositories

    check_environment_variables()
    results = Results()

    # list of repositories to check
    results.repositories = repositories

    # we need to know which tables are enabled or disabled to proper process the template
    results.sla_table_enabled = sla_table_enabled
    results.liveness_table_enabled = liveness_table_enabled
    results.code_quality_table_enabled = code_quality_table_enabled
    results.ci_jobs_table_enabled = ci_jobs_table_enabled

    results.teams = teams
    results.sprint = config.get_sprint()
    print("Sprint: " + results.sprint)

    ci_jobs = CIJobs()
    job_statuses = read_job_statuses(ci_jobs, ci_jobs_table_enabled, liveness_table_enabled)

    results.smoke_tests_total_builds, results.smoke_tests_success_builds = \
        production_smoketests_status(ci_jobs)

    results.sprint_plan_url = config.get_sprint_plan_url()

    for team in teams:
        results.issues_list_url[team] = config.get_list_of_issues_url(team)

    if liveness_table_enabled:
        prepare_data_for_liveness_table(results, ci_jobs, job_statuses)

    prepare_data_for_repositories(repositories, results, ci_jobs, job_statuses,
                                  clone_repositories_enabled, cleanup_repositories_enabled,
                                  code_quality_table_enabled, ci_jobs_table_enabled)

    if sla_table_enabled:
        prepare_data_for_sla_table(results)

    if code_quality_table_enabled and liveness_table_enabled:
        export_into_csv(results)

    generate_dashboard(results, ignored_files_for_pylint, ignored_files_for_pydocstyle)


if __name__ == "__main__":
    # execute only if run as a script
    main()
