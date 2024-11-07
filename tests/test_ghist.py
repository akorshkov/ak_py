"""Test ghist module.

ghist module fetches and reports history of commits and builds for specified bug(s).
"""
import unittest
import io
import json
import logging

from ak.ghist import ProjectRepo, ReposCollection, BuildNumData
from ak.color import ColoredText
from ak.logtools import logs_configure

from .mock_git import MockedGitRepo


#########################
# helpers for testing git repo struture

class CommitsCheckerMixin:
    """Helper methods for testing report data based on MockedGitRepo."""

    def check_printed_report_requirements(self, report):
        """Verify that the report can be printed and make some checks of result."""

        with io.StringIO() as output:
            print(report, file=output)
            print_result = output.getvalue()

        # make sure there are no trailing spaces
        plain_text = ColoredText.strip_colors(print_result)
        for i, line in enumerate(plain_text.split("\n")):
            self.assertFalse(
                line.endswith(" "),
                f"trailing spaces detected in line {i} of the report:\n"
                f"|{line}|\nWhole report:\n{print_result}")

    def assert_branches_list(self, rgraph, expected_branches_names, message=None):
        """Verify that RGraph contains branches with specified names"""
        actual_branches_list = [
            rbranch.branch_name for rbranch in rgraph.branches]
        self.assertEqual(expected_branches_names, actual_branches_list, message)

    def assert_buildnums(self, builds_list, expected_buildnums, message=None):
        """Check numbers of builds in builds_list.

        Arguments:
        - builds_list: [RBuild, ] or [BuildNumData, ]
        - expected_buildnums: list of srings like ["10.250.4303", ...]
        """
        if builds_list and hasattr(builds_list[0], 'build_num'):
            actual_buildnums = [str(b.build_num) for b in builds_list]
        else:
            actual_buildnums = [str(b) for b in builds_list]
        self.assertEqual(expected_buildnums, actual_buildnums, message)

    def assert_incl_at(self, rbuild, expected_incl_at, message=None):
        """Check contents of rbuild.included_at

        Arguments:
        - rbuild: RBuild
        - expected_incl_at: {("repo_name", "relsease/10.5", "10.5.3"), }
        """
        actual_incl_at = {
            (str(x[0]), str(x[1]), str(x[2]))
            for x in rbuild.included_at}
        self.assertEqual(expected_incl_at, actual_incl_at, message)

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

    def _read_saved_build_num_from_file(self, blob, path):
        # reads major.minor.build from file.
        # build part is optional.
        data = blob.data_stream.read().decode().strip()
        nums = [int(chunk) for chunk in data.split('.')]
        if len(nums) == 2:
            nums.append(None)
        major, minor, patch = nums
        return BuildNumData(major, minor, patch)

    def read_components_from_file(self, v_file_path, blob):
        """Read components versions from mocked blob.

        File contents is expected to be json like:
        '{"cmpnt": "10.120.2010", "other_cmpnt": "2.3.5"}'
        """
        assert v_file_path == 'DEPENDS'  # this 'file' is used in test repos
        d = json.load(blob.data_stream)
        result = {}
        for cmpnt, version_str in d.items():
            nn = version_str.split('.')
            assert len(nn) == 3, (
                f"component {cmpnt}: invalid version '{version_str}'")
            major_minor_patch = [int(n) for n in nn]
            result[cmpnt] = major_minor_patch
        return result


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
            'comp_1': StdTestRepo('comp_1', component_1_git_repo, 'origin'),
        })
        # logs_configure(5)

    def test_empty_report(self):
        """Test empty report: no report-related commits found."""
        report = self.repos.make_report("BUG-xxx")
        self.check_printed_report_requirements(report)

        self.assertEqual(1, len(report.data))
        cmpnt_name, rgraph = report.data[0]
        self.assertEqual("comp_1", cmpnt_name)
        # self.assertEqual(0, len(rgraph.branches), "empty report expected")
        self.assertEqual(0, len(rgraph.rcommits), "empty report expected")

    def test_single_commit_built_later(self):
        """Single commit matches, included in build based on different commit."""
        report = self.repos.make_report("BUG-111")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-222")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
            report = self.repos.make_report(pattern)
            self.check_printed_report_requirements(report)

            _, rgraph = report.data[0]
            self.assert_branches_list(rgraph, ['master', ])
            rbranch = rgraph.branches[0]
            rbuilds = rbranch.get_rbuilds_list()
            self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
            rbuild = rbuilds[0]
            self.assert_commits_list(rbuild, [expected_commit_id, ])

    def test_report_multiple_commits(self):
        """Multiple commits in report; multiple builds."""
        report = self.repos.make_report("BUG")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
            "--> |file:VERSION:10.270|",
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
            'comp_1': StdTestRepo('comp_1', component_1_git_repo, 'origin'),
        })
        # logs_configure(5)

    def test_report_111(self):
        """Verify data for 'BUG-111' report."""
        report = self.repos.make_report("BUG-111")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-122")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-133")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-144")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-155")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-166")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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
        report = self.repos.make_report("BUG-177")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
        self.assert_branches_list(rgraph, ["master", ])

        # check branch master
        rbranch = rgraph.branches[0]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["8888.8888.8888", ])
        self.assert_commits_list(rbuilds[0], [340, ])

    def test_report_all_bugs(self):
        """Verify data for all bugs 'BUG' report."""
        report = self.repos.make_report("BUG")
        self.check_printed_report_requirements(report)

        _, rgraph = report.data[0]
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


class TestReposDependentComponent(unittest.TestCase, CommitsCheckerMixin):
    """Case with two repositories: one is component of the other."""

    def setUp(self):
        # processing of repos here logs warnings. Disable it.
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_component_bumps_reporting(self):
        """Test miscelaneous scenarios of component bumps."""
        # 'BUG-211' is included into two builds in proj_lib:
        # 10.120.2020 and 10.130.3090
        #
        # c_master repo has two branches: release/5.4 and master
        # release/5.4 contains proj_lib==10.120.2020
        # master contains proj_lib==10.130.3090, but it's not in build yet
        # logs_configure(5)
        # component repo
        master_repo = MockedGitRepo(
            'branch: origin/master',  # ---- branch master
            '990<-10|branch master head',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2019"}',
            'branch: origin/release/5.7',  # ---- branch 5.7
            '490|branch 5.7 head - not a build',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2019"}',
            '480<-10|build 5.7.77',
            '--> |tags:build_77_release_5_7_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2019"}',
            'branch: origin/release/5.6',  # ---- branch 5.6
            '390<-10|branch 5.6 head',
            '--> |tags:build_67_release_5_6_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2019"}',
            'branch: origin/release/5.5',  # ---- branch 5.5
            '290<-10|branch 5.5 head',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2010"}',
            'branch: origin/release/5.4',  # ---- branch 5.4
            '128|head of branch',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2018"}',
            '127|build 17|tags: build_17_release_5_4_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2017"}',
            '124|build 14|tags: build_14_release_5_4_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2014"}',
            '121|build 11|tags: build_11_release_5_4_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2011"}',
            '120|build 10|tags: build_10_release_5_4_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2010"}',
            'branch: origin/release/5.3',  # -- branch 5.3
            '90|build 5|tags: build_5_release_5_3_success',
            '--> |file:DEPENDS:{"proj_lib": "10.120.2010"}',
            '10|build 3|tags: build_3_release_5_3_success',
            '--> |file:DEPENDS:{"proj_lib": "10.110.2020"}',
            name="c_master",
        )

        cmpnt_repo = MockedGitRepo(
            'branch: origin/master',  # ---- branch
            '990 | final_build |tags: build_3090_release_10_130_success',
            '--> |file:VERSION:10.130|',
            'branch: origin/release/10.120',  # ---- branch
            '190 | BUG-211 g |tags: build_2019_release_10_120_success',
            '180 | BUG-211 f |tags: build_2018_release_10_120_success',
            '160 | BUG-211 e |tags: build_2016_release_10_120_success',
            '150 | BUG-211 d |tags: build_2015_release_10_120_success',
            '140 | no bug    |tags: build_2014_release_10_120_success',
            '130 | BUG-211 c |tags: build_2013_release_10_120_success',
            '120 | BUG-211 b |tags: build_2012_release_10_120_success',
            '110 | BUG-211 a |tags: build_2011_release_10_120_success',
            '100 | some build |tags: build_2010_release_10_120_success',
            name="proj_lib",
        )

        class MassterProjectRepo(StdTestRepo):
            _COMPONENTS_VERSIONS_LOCATIONS = {
                'proj_lib': 'DEPENDS',
            }

        class DemoRepoCollection2(ReposCollection):
            _REPOS_TYPES = {
                'c_master': MassterProjectRepo,
                'proj_lib': StdTestRepo,
            }

        repos = DemoRepoCollection2({
            'c_master': MassterProjectRepo('c_master', master_repo, 'origin'),
            'proj_lib': StdTestRepo('proj_lib', cmpnt_repo, 'origin'),
        })

        # repos prepared
        report = repos.make_report("BUG-211")
        rgraphs_by_name = {
            repo_name: rgraph for repo_name, rgraph in report.data}
        self.check_printed_report_requirements(report)

        self.assertEqual({'c_master', 'proj_lib'}, rgraphs_by_name.keys())

        # test is mostly interested in structure of report for c_master
        # but first make sure component data is as expected
        c_lib_rgraph = rgraphs_by_name['proj_lib']
        self.assert_branches_list(
            c_lib_rgraph, ["master", "release/10.120"])
        self.assert_buildnums(
            c_lib_rgraph.branches[1].get_rbuilds_list(),  # release/10.120
            [
                "10.120.2019", "10.120.2018", "10.120.2016",
                "10.120.2015", "10.120.2013", "10.120.2012", "10.120.2011",
            ])
        self.assert_buildnums(
            c_lib_rgraph.branches[0].get_rbuilds_list(),  # master
            ["10.130.3090", ])

        # now to c_master. It does not contain any commits explicitely
        # related to report topic, only bumps of component proj_lib
        c_master_rgraph = rgraphs_by_name['c_master']
        self.assert_branches_list(
            c_master_rgraph,
            ["master", "release/5.7", "release/5.6", "release/5.4"],
            "branches release/5.3 and release/5.5 do not contain any "
            "report-related builds of proj_lib component",
        )
        br_by_name = c_master_rgraph.get_rbranches_by_name()

        # check branch release/5.4 ===================================
        #
        # This branch contains several builds:
        # 5.4.10 - NOT reported:
        #   includes proj_lib=10.120.2010 which is not report-related
        # 5.4.11 - reported:
        #   includes proj_lib=10.120.2011
        # 5.4.14 - reported:
        #   includes proj_lib=10.120.2014 - it is not report related itself
        #   but bump brings proj_lib=10.120.2012 and proj_lib=10.120.2013
        # 5.4.17 - NOT reported:
        #   includes proj_lib=10.120.2017 - info about this build is missing
        # 8888.8888.8888 - not built - reported:
        #   includes 10.120.2018
        # 9999.9999.9999 - not merged - reported:
        #   includes 10.120.2019
        rbranch = br_by_name["release/5.4"]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["9999.9999.9999", "8888.8888.8888", "5.4.14", "5.4.11"],
        )

        # bump in "5.4.11"
        bump = rbuilds[3].bumps['proj_lib']
        self.assertEqual("10.120.2011", str(bump.to_buildnum))
        self.assert_buildnums([], bump.from_build_nums)

        # bump in "5.4.14"
        bump = rbuilds[2].bumps['proj_lib']
        self.assertEqual("10.120.2014", str(bump.to_buildnum))
        self.assert_buildnums(bump.from_build_nums, ["10.120.2011"])

        # bump in "not built" build
        bump = rbuilds[1].bumps['proj_lib']
        self.assertEqual("10.120.2018", str(bump.to_buildnum))
        self.assert_buildnums(bump.from_build_nums, ["10.120.2014"])

        # bump in "not merged" build
        bump = rbuilds[0].bumps['proj_lib']
        self.assertEqual("10.120.2019", str(bump.to_buildnum))
        self.assert_buildnums(bump.from_build_nums, ["10.120.2018"])

        # check c_master release/5.5 branch ==========================
        #
        # There are no builds in this branch at all. Not in report.
        self.assertNotIn("release/5.5", br_by_name)

        # check c_master release/5.6 branch ==========================
        #
        # no 'fake' builds required. Situation is similar to release/5.7
        # but latest build was created not from a head commit
        rbranch = br_by_name["release/5.6"]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["5.6.67"],)

        bump = rbuilds[0].bumps['proj_lib']
        self.assertEqual("10.120.2019", str(bump.to_buildnum))
        self.assert_buildnums([], bump.from_build_nums)

        # check c_master release/5.7 branch ==========================
        #
        # no 'fake' builds required
        rbranch = br_by_name["release/5.7"]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(rbuilds, ["5.7.77"],)

        bump = rbuilds[0].bumps['proj_lib']
        self.assertEqual("10.120.2019", str(bump.to_buildnum))
        self.assert_buildnums([], bump.from_build_nums)

        # check c_master master branch ===============================
        #
        # only fake "not built" build is present
        rbranch = br_by_name["master"]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["8888.8888.8888", ],
        )

        # bump in "not built" build
        bump = rbuilds[0].bumps['proj_lib']
        self.assertEqual("10.120.2019", str(bump.to_buildnum))
        self.assert_buildnums(bump.from_build_nums, [])

    def test_included_at_data_in_component(self):
        """Check that builds of component are included into correct builds of parent"""
        master_repo = MockedGitRepo(
            'branch: origin/release/5.5',  # ---- branch 5.5
            '590 |branch 5.5 head',
            '--> |file:DEPENDS:{"proj_lib": "10.20.7"}',
            '550 |build 5.5.5',
            '--> |tags: build_5_release_5_5_success',
            '--> |file:DEPENDS:{"proj_lib": "10.20.4"}',
            'branch: origin/release/5.4',  # ---- branch 5.4
            '390<-10|branch 5.4 head',
            '--> |tags:build_47_release_5_4_success',
            '--> |file:DEPENDS:{"proj_lib": "10.20.7"}',
            'branch: origin/release/5.3',  # ---- branch 5.3
            '90|build 5|tags: build_5_release_5_3_success',
            '--> |file:DEPENDS:{"proj_lib": "10.20.1"}',
            '10|build 3|tags: build_3_release_5_3_success',
            '--> |file:DEPENDS:{"proj_lib": "10.10.1"}',
            name="c_master",
        )

        cmpnt_repo = MockedGitRepo(
            'branch: origin/master',  # ---- branch
            '990 | final_build |tags: build_3090_release_10_130_success',
            '--> |file:VERSION:10.130|',
            'branch: origin/release/10.20',  # ---- branch
            '190 | BUG-212 g |tags: build_9_release_10_20_success',
            '170 | BUG-212 f |tags: build_7_release_10_20_success',
            '150 | BUG-212 d |tags: build_5_release_10_20_success',
            '140 | no bug    |tags: build_4_release_10_20_success',
            '120 | BUG-212 b |tags: build_3_release_10_20_success',
            '110 | BUG-212 a |tags: build_2_release_10_20_success',
            '100 | some build |tags: build_1_release_10_20_success',
            name="proj_lib",
        )

        class MassterProjectRepo(StdTestRepo):
            _COMPONENTS_VERSIONS_LOCATIONS = {
                'proj_lib': 'DEPENDS',
            }

        class DemoRepoCollection3(ReposCollection):
            _REPOS_TYPES = {
                'c_master': MassterProjectRepo,
                'proj_lib': StdTestRepo,
            }

        repos = DemoRepoCollection3({
            'c_master': MassterProjectRepo('c_master', master_repo, 'origin'),
            'proj_lib': StdTestRepo('proj_lib', cmpnt_repo, 'origin'),
        })

        # repos prepared
        report = repos.make_report("BUG-212")
        rgraphs_by_name = {
            repo_name: rgraph for repo_name, rgraph in report.data}
        self.check_printed_report_requirements(report)

        # proj_lib repo: verify 'included_at' info is populated correctly.
        #
        # There are following builds in this component (all in release/10.120
        # branch, structure is simple linear):
        #
        # 10.20.1, 10.20.2, 10.20.3, 10.20.5, 10.20.7, 10.20.9

        # builds in proj_lib release/10.20
        c_lib_rgraph = rgraphs_by_name['proj_lib']
        self.assert_branches_list(
            c_lib_rgraph, ["master", "release/10.20"])
        rbuilds = {
            str(rb.build_num): rb
            for rb in c_lib_rgraph.branches[1].get_rbuilds_list()}
        self.assertEqual(
            rbuilds.keys(),
            {
                "10.20.2", "10.20.3", "10.20.5", "10.20.7", "10.20.9",
            })

        self.assert_incl_at(
            rbuilds["10.20.2"], {
                ('c_master', 'release/5.4', '5.4.47'),
                ('c_master', 'release/5.5', '5.5.5'),
            })

        self.assert_incl_at(
            rbuilds["10.20.3"], {
                ('c_master', 'release/5.4', '5.4.47'),
                ('c_master', 'release/5.5', '5.5.5'),
            })

        self.assert_incl_at(
            rbuilds["10.20.5"], {
                ('c_master', 'release/5.4', '5.4.47'),
                ('c_master', 'release/5.5', '8888.8888.8888'),
            })

        self.assert_incl_at(
            rbuilds["10.20.7"], {
                ('c_master', 'release/5.4', '5.4.47'),
                ('c_master', 'release/5.5', '8888.8888.8888'),
            })

        self.assert_incl_at(rbuilds["10.20.9"], set())

    def test_branch_wo_component_version(self):
        """Corner case: component has no builds in some branch yet."""

        cmpnt_repo = MockedGitRepo(
            'branch: origin/master',  # ---- branch
            '900 <- 310 | branch ',
            'branch: origin/release/22.11',  # ---- branch
            '310 | build me |tags: build_2_release_22_11_success',
            '300 <- 220 | branch 22.11',
            'branch: origin/release/22.10',  # ---- branch
            '220 | current 22.10 head',
            '210 | BUG-42 x1',  # but there is no build in this branch
            '200 <- 120 | branch 22.10',
            'branch: origin/release/22.09',  # ---- branch
            '120 | build me |tags: build_1_release_22_09_success',
            '110 | BUG-42',
            '100 | initial commit',
            name="proj_lib",
        )

        master_repo = MockedGitRepo(
            'branch: origin/master',  # ---- branch
            '900 <- 310 | branch ',
            'branch: origin/release/22.11',  # ---- branch
            '310 | include fix here',
            '--> |file:DEPENDS:{"proj_lib": "22.11.2"}',
            '300 <- 220| branch 22.11',
            'branch: origin/release/22.10',  # ---- branch
            '220 | current head of 22.10',
            '210 | BUG-42 some fixes in owner repo',
            '200 <- 100| branch 22.10',
            '--> |file:DEPENDS:{"proj_lib": "22.09.1"}',
            'branch: origin/release/22.09',  # ---- branch
            '100 | initial commit',
            name="c_master",
        )

        class MassterProjectRepo(StdTestRepo):
            _COMPONENTS_VERSIONS_LOCATIONS = {
                'proj_lib': 'DEPENDS',
            }

        class DemoRepoCollection3(ReposCollection):
            _REPOS_TYPES = {
                'c_master': MassterProjectRepo,
                'proj_lib': StdTestRepo,
            }

        repos = DemoRepoCollection3({
            'c_master': MassterProjectRepo('c_master', master_repo, 'origin'),
            'proj_lib': StdTestRepo('proj_lib', cmpnt_repo, 'origin'),
        })

        # main part of test: next command should not fail
        report = repos.make_report("BUG-42")
        rgraphs_by_name = {
            repo_name: rgraph for repo_name, rgraph in report.data}
        self.check_printed_report_requirements(report)

        self.assertEqual({'c_master', 'proj_lib'}, rgraphs_by_name.keys())

        # test is mostly interested in structure of report for c_master
        # but first make sure component data is as expected
        c_lib_rgraph = rgraphs_by_name['proj_lib']
        self.assert_branches_list(
            c_lib_rgraph, ["master", "release/22.11", "release/22.10", "release/22.09"])

        # now test c_master
        c_master_rgraph = rgraphs_by_name['c_master']
        self.assert_branches_list(
            c_master_rgraph, ["master", "release/22.11", "release/22.10"])
        br_by_name = c_master_rgraph.get_rbranches_by_name()

        rbranch = br_by_name["release/22.10"]
        rbuilds = rbranch.get_rbuilds_list()
        self.assert_buildnums(
            rbuilds, ["8888.8888.8888"],
        )

        # bumps in fake 'not-yet-built' build of 22.10
        bumps = rbuilds[0].bumps

        self.assertNotIn(
            'proj_lib', bumps,
            f"'proj_lib' should not be in bumps list because in branch 22.10 there are "
            f"no report-related build of 'proj_lib' at all. Actual bumps: {bumps}"
        )
