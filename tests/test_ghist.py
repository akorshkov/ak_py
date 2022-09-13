"""Test ghist module.

ghist module fetches and reports history of commits and builds for specified bug(s).
"""
import unittest

from ak.ghist import ProjectRepo, ReposCollection
from ak.logtools import logs_configure

from .mock_git import MockedGitRepo


#########################
# helpers for testing git repo struture

class CommitsCheckerMixin:
    """Helper methods for testing report data based on MockedGitRepo."""

    def assert_branches_list(self, rgraph, expected_branches_names, message=None):
        """Verify that RGraph contains branches with specified names"""
        actual_branches_list = [
            rbranch.branch_name for rbranch in rgraph.branches]
        self.assertEqual(expected_branches_names, actual_branches_list, message)

    def assert_buildnums(self, rbuilds_list, expected_buildnums, message=None):
        """Verify that RBranch contains info about specified build numbers.

        Arguments:
        - rbuilds_list: [RBuild, ]
        - expected_buildnums: list of srings like ["10.250.4303", ...]
        """
        actual_buildnums = [str(b.build_num) for b in rbuilds_list]
        self.assertEqual(expected_buildnums, actual_buildnums, message)

    def assert_rbuild_commits(self, rbuild, expected_intids_set, message=None):
        """Check commits included into RBuild.

        It is supposed that 'rbuild' is a part of report generated on
        test repo MockedGitRepo; commit objects in this repo have
        unique attribute 'intid'.

        Arguments:
        - rbuild: RBuild object, part of generated report
        - expected_intids_set: {int, }
        """
        actual_commits_intids = {
            rc.commit.intid for rc in rbuild.rcommits.values()}
        if actual_commits_intids != expected_intids_set:
            extra_intids = actual_commits_intids - expected_intids_set
            missing_intids = expected_intids_set - actual_commits_intids
            msg = f"Unexpected set of commits in rbuild: \n" + "\n".join(
                str(rbuild.rcommits[iid].commit)
                for iid in sorted(rbuild.rcommits.keys(), reverse=True))
            if extra_intids:
                msg += f"\n extra ids: {extra_intids}"
            if missing_intids:
                msg += f"\n missing ids: {missing_intids}"
            if message is not None:
                msg += f"\n {message}"
            raise AssertionError(msg)

    def assert_commits_list(self, rbuild, expected_intids_list, message=None):
        """Test list of printable commits included into RBuild.

        It is supposed that 'rbuild' is a part of report generated on
        test repo MockedGitRepo; commit objects in this repo have
        unique attribute 'intid'.

        Arguments:
        - rbuild: RBuild object, part of generated report
        - expected_intids_list: [int, ]
        """
        printable_commits = rbuild.get_printable_rcommits()
        actual_commits_intids = [
            rc.commit.intid for rc in printable_commits]
        if actual_commits_intids != expected_intids_list:
            msg = f"Unexpected list of printable commits in rbuild: \n" + "\n".join(
                str(rc.commit) for rc in printable_commits)
            if message is not None:
                msg += f"\n {message}"
            self.assertEqual(
                actual_commits_intids, expected_intids_list, msg)


#########################
# StdTestRepo

class StdTestRepo(ProjectRepo):
    """Standard Project repo to be used in tests."""
    _SAVED_BUILD_NUM_SOURCES = ["VERSION", ]

    def _read_saved_build_numbers_from_file(self, blob, path):
        # reads major.minor.build from file.
        # build part is optional.
        data = blob.data_stream.read().decode().strip()
        nums = [int(chunk) for chunk in data.split('.')]
        if len(nums) == 2:
            nums.append(None)
        return nums


#########################
# Test simple scenarios with a single repo

class TestSingleRepoSingleBranch(unittest.TestCase, CommitsCheckerMixin):
    """Tests on primitive setup: one repo, linear history of commits."""

    @classmethod
    def setUpClass(cls):
        component_1_git_repo = MockedGitRepo(
            "branch: origin/master",
            "50 | BUG-555",
            "40 | BUG-444",
            "30 | BUG-333|tags: build_4304_release_10_250_success ",
            "20 | BUG-222|tags: build_4303_release_10_250_success",
            "10 | BUG-111",
            "5  | Initial Commit",
            name="component_1",
        )

        class DemoRepoCollection1(ReposCollection):
            _REPOS_TYPES = {
                'comp_1': StdTestRepo,
            }

        cls.repos = DemoRepoCollection1({
            'comp_1': StdTestRepo('comp_1', component_1_git_repo),
        })
        # logs_configure(5)

    def test_empty_report(self):
        """Test empty report: no report-related commits found."""
        reports_data = self.repos.make_reports_data("BUG-xxx")
        #self.repos.print_prepared_reports(reports_data)

        self.assertEqual(1, len(reports_data))
        cmpnt_name, rgraph = reports_data[0]
        self.assertEqual("comp_1", cmpnt_name)
        # self.assertEqual(0, len(rgraph.branches), "empty report expected")
        self.assertEqual(0, len(rgraph.rcommits), "empty report expected")

    def test_single_commit_built_later(self):
        """Single commit matches, included in build based on different commit."""
        reports_data = self.repos.make_reports_data("BUG-111")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ['master', ])
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.250.4303", ])
        rbuild = rbuilds[0]

        commits_intids_in_build = {rc.commit.intid for rc in rbuild.rcommits.values()}
        self.assert_rbuild_commits(
            rbuild, {10, 20},
            "commit 10 - explicitely selected, commit 20 - build, which includes it")
        self.assert_commits_list(rbuild, [10, ], "only commit 10 is printable")

    def test_single_commit_built_immediately(self):
        """Single commit matches, included in build based on same commit."""
        reports_data = self.repos.make_reports_data("BUG-222")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ['master', ])
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.250.4303", ])
        rbuild = rbuilds[0]
        self.assert_commits_list(rbuild, [20, ], "only commit 20 matches")

    def test_commit_not_built(self):
        """Single commit matches, not included into builds yet."""
        for pattern, expected_commit_id in [
            ("BUG-444", 40),
            ("BUG-555", 50),
        ]:
            reports_data = self.repos.make_reports_data(pattern)
            # self.repos.print_prepared_reports(reports_data)

            _, rgraph = reports_data[0]
            self.assert_branches_list(rgraph, ['master', ])
            rbranch = rgraph.branches[0]
            rbuilds = rbranch.get_rbuilds_list()
            self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
            rbuild = rbuilds[0]
            self.assert_commits_list(rbuild, [expected_commit_id, ])

    def test_report_multiple_commits(self):
        """Multiple commits in report; multiple builds."""
        reports_data = self.repos.make_reports_data("BUG")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ['master', ])
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["8888.8888.8888", "10.250.4304", "10.250.4303", ])
        self.assert_commits_list(rbuilds[0], [50, 40])
        self.assert_commits_list(rbuilds[1], [30, ])
        self.assert_commits_list(rbuilds[2], [20, 10])


class TestSingleRepoMultyBranch(unittest.TestCase, CommitsCheckerMixin):
    """One repo several branches."""

    @classmethod
    def setUpClass(cls):
        component_1_git_repo = MockedGitRepo(
            "branch: origin/master",  # ---- branch
            "340 | BUG-177",
            "330<-230, 320| merge",
            "320<-220| branch out |tags: build_4500_master_success",
            "--> file:VERSION:10.270|",
            "branch: origin/release/10.260",  # ---- branch
            "240<-230, 140| merge|tags: build_4445_release_10_260_success",
            "230 | BUG-133|tags: build_4444_release_10_260_success",
            "225 | BUG-166",
            "220<-120 | first commit after branch",
            "branch: origin/release/10.250",  # ---- branch
            "150 | BUG-155",
            "140 | BUG-144",
            "130 | BUG-133|tags: build_4304_release_10_250_success ",
            "120 | BUG-122|tags: build_4303_release_10_250_success",
            "110 | BUG-111",
            "15  | Initial Commit",
            name="component_1",
        )

        class DemoRepoCollection(ReposCollection):
            _REPOS_TYPES = {
                'comp_1': StdTestRepo,
            }

        cls.repos = DemoRepoCollection({
            'comp_1': StdTestRepo('comp_1', component_1_git_repo),
        })
        # logs_configure(5)

    def test_report_111(self):
        """Verify data for 'BUG-111' report."""
        reports_data = self.repos.make_reports_data("BUG-111")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.250.4303", ])
        self.assert_commits_list(rbuilds[0], [110, ])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.260.4444", ])
        self.assert_commits_list(rbuilds[0], [110, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.270.4500", ])
        self.assert_commits_list(rbuilds[0], [110, ])

    def test_report_222(self):
        """Verify data for 'BUG-122' report."""
        reports_data = self.repos.make_reports_data("BUG-122")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.250.4303", ])
        self.assert_commits_list(rbuilds[0], [120, ])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.260.4444", ])
        self.assert_commits_list(rbuilds[0], [120, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.270.4500", ])
        self.assert_commits_list(rbuilds[0], [120, ])

    def test_report_333(self):
        """Verify data for 'BUG-133' report."""
        reports_data = self.repos.make_reports_data("BUG-133")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(
            rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.250.4304", ])
        self.assert_commits_list(rbuilds[0], [130, ])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.260.4445", "10.260.4444"])
        self.assert_commits_list(rbuilds[0], [130, ])
        self.assert_commits_list(rbuilds[1], [230, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["9999.9999.9999", "8888.8888.8888"])
        self.assert_commits_list(
            rbuilds[0], [130, ],
            "commit 130 merged into 10.260 by commit 240 and not merged into master")
        self.assert_commits_list(rbuilds[1], [230, ])

    def test_report_444(self):
        """Verify data for 'BUG-144' report."""
        reports_data = self.repos.make_reports_data("BUG-144")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(
            rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
        self.assert_commits_list(rbuilds[0], [140, ])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.260.4445", ])
        self.assert_commits_list(rbuilds[0], [140, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["9999.9999.9999", ])
        self.assert_commits_list(rbuilds[0], [140, ])

    def test_report_555(self):
        """Verify data for 'BUG-155' report."""
        reports_data = self.repos.make_reports_data("BUG-155")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(
            rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
        self.assert_commits_list(rbuilds[0], [150, ])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["9999.9999.9999", ])
        self.assert_commits_list(rbuilds[0], [150, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["9999.9999.9999", ])
        self.assert_commits_list(rbuilds[0], [150, ])

    def test_report_666(self):
        """Verify data for 'BUG-166' report."""
        reports_data = self.repos.make_reports_data("BUG-166")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(
            rgraph, ["master", "release/10.260"])

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["10.260.4444", ])
        self.assert_commits_list(rbuilds[0], [225, ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
        self.assert_commits_list(rbuilds[0], [225, ])

    def test_report_777(self):
        """Verify data for 'BUG-177' report."""
        reports_data = self.repos.make_reports_data("BUG-177")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(rgraph, ["master", ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
        self.assert_commits_list(rbuilds[0], [340, ])

    def test_report_all_bugs(self):
        """Verify data for all bugs 'BUG' report."""
        reports_data = self.repos.make_reports_data("BUG")
        # self.repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assert_branches_list(
            rgraph, ["master", "release/10.260", "release/10.250"])

        # check branch release/10.250
        rbranch = rgraph.branches[2]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["8888.8888.8888", "10.250.4304", "10.250.4303"])
        self.assert_commits_list(rbuilds[0], [150, 140])  # not built
        self.assert_commits_list(rbuilds[1], [130, ])  # build 10.250.4304
        self.assert_commits_list(rbuilds[2], [120, 110])  # build 10.250.4303

        # check branch release/10.260
        rbranch = rgraph.branches[1]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["9999.9999.9999", "10.260.4445", "10.260.4444"])
        self.assert_commits_list(rbuilds[0], [150])  # not merged
        self.assert_commits_list(rbuilds[1], [140, 130])  # 10.260.4445
        self.assert_commits_list(rbuilds[2], [230, 225, 120, 110])  # 10.260.4444

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["9999.9999.9999", "8888.8888.8888", "10.270.4500"])
        self.assert_commits_list(rbuilds[0], [150, 140, 130])  # not merged
        self.assert_commits_list(rbuilds[1], [340, 230, 225])  # not built
        self.assert_commits_list(rbuilds[2], [120, 110])  # 10.270.4500
