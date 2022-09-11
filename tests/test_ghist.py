"""Test ghist module.

ghist module fetches and reports history of commits and builds for specified bug(s).
"""
import unittest
import io
from hashlib import sha1
import random

from ak.ghist import ProjectRepo, ReposCollection
from ak.logtools import logs_configure


#########################
# MockedGitRepo - in-memory primitive git repo.
#
# only mocks commits structure of git repo - no files actually
# committed.

class _MockedAuthor:
    # internal part of _MockedGitCommit
    __slots__ = ('name', )
    def __init__(self, name):
        self.name = name


class _MockedBlob:
    # mock git blob
    def __init__(self, contents):
        self.hexsha = sha1(contents.encode()).hexdigest()
        self.data = contents.encode() if isinstance(contents, str) else contents

    @property
    def data_stream(self):
        return io.BytesIO(self.data)


class _MockedTree:
    # mock of git.commit.tree
    def __init__(self, files_contents):
        self.files_in_tree = {
            path: _MockedBlob(contents)
            for path, contents in files_contents.items()
        }

    def __truediv__(self, path):
        # mock "git.commit.tree / path" operation.
        # returns blob (actually _MockedBlob)
        return self.files_in_tree[path]


class _MockedGitCommit:
    # mocked git commit object
    _AUTHORS = [
        "V. Arnold", "Arnold Sh.", "Richard Feynman", "J. Morrison",
        "Norris, Chuck", "Elieser Yudkowsky",
    ]
    _BASE_TIME = random.randint(10000, 20000) * 86400

    def __init__(self, intid, parents, message, tags, tree, repo_name):
        self.intid = intid  # integer id, should be unique within a repo
        s = f"{self.intid:05}"

        # generate hexhsa unique, repeatable and indicating intid of commit
        hs = sha1((repo_name + s).encode()).hexdigest()
        self.hexsha = hs[:1] + s[-5:] + hs[6:]
        self.parents = parents  # [_MockedGitCommit, ]
        self.message = message
        self.tree = _MockedTree(tree)

        # note: actual git.commit object does not have 'tags' attribute
        self.tags = tags

        # following attributes are used for printing out results
        # and do not affect report structure.
        self.committed_date = self._BASE_TIME + self.intid * 47 + random.randint(0, 40)
        self.author = _MockedAuthor(random.choice(self._AUTHORS))

    def __str__(self):
        return f"MockedCommit({self.intid} {self.hexsha[:11]} {self.message})"

    def __repr__(self):
        return str(self)


class _MockedGitRef:
    # part of MockedGitRepo
    # keeps info about a commit associated with ref
    __slots__ = 'name', 'head_commit', 'hexsha'
    def __init__(self, name, head_commit):
        self.name = name
        self.head_commit = head_commit
        self.hexsha = head_commit.hexsha


class _MockedGitRemote:
    # mocks element of git.Repo.remotes collection.
    # (contains refs associated with this remote)
    __slots__ = ('refs', )
    def __init__(self, repo, name):
        """Info about a single element of git.Repo.remotes collection.

        Arguments:
        - repo: MockedGitRepo
        - name: name of the remote (f.e. 'origin')

        Constructor reads all the info related to specified origin from 'repo'
        """
        # ref_name 'refs/remotes/origin/master' in Repo corresponds to
        # ref_name 'origin/master' here. This is consistent with GitPython behavior
        prefix = f"refs/remotes/{name}/"
        chopofflen = len("refs/remotes/")
        refs_by_name = {}
        for ref_name, ref in repo.refs.items():
            if ref_name.startswith(prefix):
                ref_name = ref_name[chopofflen:]
                refs_by_name[ref_name] = _MockedGitRef(ref_name, ref.head_commit)
        self.refs = [
            refs_by_name[ref_name]
            for ref_name in sorted(refs_by_name)
        ]


class MockedGitRepo:
    """In-memory primitive git repo for testing purposes."""

    def __init__(self, *commits_descr, name):
        """Construct MockedGitRepo.

        Arguments:
        - commits_descr: strings with description of 'commits' in the repo.
        - name: string (affects generated hexsha of commits)

        Example:
            "branch: origin/master",
            "100<-20, 40| BUG-77|tags: build_4304_release_10_250_success ",
            "  20<-10   | BUG-2525  |tags: build_4303_release_10_250_success",
            "40         | Some Commit",
            "10         | Initial Commit",

        (leading and trailing spaces in each section are ignored)
        """
        self.name = name
        self.all_commits = {}
        self.refs = {}

        # parse the commits descriptions
        prev_commit = None
        extra_lines = []  # used in case if commit description takes several lines
        for descr_line in reversed(commits_descr):
            descr_line = descr_line.strip()
            if not descr_line:
                continue
            if descr_line.startswith("branch:"):
                branch_name = descr_line[7:].strip()  # "origin/release/10.250"
                assert prev_commit is not None, (
                    f"no head commit for branch '{branch_name}' found")
                ref_name = "refs/remotes/" + branch_name
                assert ref_name not in self.refs
                self.refs[ref_name] = _MockedGitRef(ref_name, prev_commit)
                continue
            if descr_line.startswith("-->"):
                extra_lines.append(descr_line[3:])
                continue

            # create new commit from description lines
            full_descr = descr_line + "|" + "|".join(reversed(extra_lines))
            extra_lines = []
            commit = self._mk_commit(full_descr, prev_commit)
            assert commit.intid not in self.all_commits, (
                f"duplicate commit intid: {commit.intid}")
            self.all_commits[commit.intid] = commit
            if commit.tags is not None:
                for tag in commit.tags:
                    tag_ref_name = "refs/tags/" + tag
                    assert tag_ref_name not in self.refs, (
                        f"duplicate tag '{tag}' detected")
                    self.refs[tag_ref_name] = _MockedGitRef(tag, commit)
            prev_commit = commit

        # finalise parents of commits
        for commit in self.all_commits.values():
            for intid in commit.parents:
                assert intid in self.all_commits, (
                    f"commit #{commit.intid} has unknown parent {intid}")
            commit.parents = [
                self.all_commits[intid] for intid in commit.parents]

        self.remotes = {'origin': _MockedGitRemote(self, 'origin')}
        self.commits_by_hexsha = {
            commit.hexsha: commit
            for commit in self.all_commits.values()
        }

    def commit(self, hexsha):
        """Get commit by hexsha - mock GitPython behavior."""
        return self.commits_by_hexsha[hexsha]

    def iter_refs(self, *prefixes):
        """yield (ref_name, hexsha) for all refs having one of specified prefixes.

        Override GitRepo's method (which fetched this info from actual git repo)
        """
        for ref_name, head_commit in self.refs.items():
            if any(ref_name.startswith(prefix) for prefix in prefixes):
                yield ref_name, head_commit.hexsha

    def _mk_commit(self, commit_descr, prev_commit):
        # commit description -> _MockedGitCommit
        chunks = [c.strip() for c in commit_descr.split('|')]
        assert len(chunks) > 1, f"invalid commit descr '{commit_descr}'"

        # chunk 0: intid and parents
        id_chunks = chunks[0].split('<-', 1)
        intid = int(id_chunks[0])
        if len(id_chunks) == 2:
            parents = [int(x) for x in id_chunks[1].split(',')]
        else:
            parents = [prev_commit.intid, ] if prev_commit is not None else []

        # get other attributes
        message = None
        tags = None
        tree = {}

        for chunk in chunks[1:]:
            if not chunk:
                # ignore empty chunk. Probably the commit_descr ends with '|' - ok
                continue
            if chunk.startswith('tags:'):
                assert tags is None, (
                    f"duplicate 'tags:' section in commit descr: {commit_descr}")
                tags = [t.strip() for t in chunk[5:].split(',')]
                continue
            if chunk.startswith('file:'):
                tree_descr_chunks = chunk.split(':')
                assert len(tree_descr_chunks) == 3, (
                    f"unexpected file contents description: '{chunk}'. "
                    f"Expected format: 'file:path/to/file:contents of the file'")
                _, path, contents = tree_descr_chunks
                path = path.strip()
                assert path not in tree, (
                    f"commit description '{commit_descr}' contains duplicate "
                    f"contents for file '{path}'")
                tree[path] = contents
                continue
            # this is message
            assert message is None, (
                f"commit descr '{commit_descr} contains duplicate 'message'"
                f"sections: '{message}' and '{chunk}'")
            message = chunk

        assert message is not None, (
            f"message is not specified in commit descr: {commit_descr}")

        return _MockedGitCommit(intid, parents, message, tags, tree, self.name)


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

        class Comp1Repo(ProjectRepo):
            pass

        class DemoRepoCollection(ReposCollection):
            _REPOS_TYPES = {
                'comp_1': Comp1Repo,
            }

        cls.repos = DemoRepoCollection({
            'comp_1': Comp1Repo('comp_1', component_1_git_repo),
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
            "340 | BUG-777",
            "330<-230, 320| merge",
            "320<-220| branch out |tags: build_4500_master_success",
            "--> file:VERSION:10.270|",
            "branch: origin/release/10.260",  # ---- branch
            "240<-230, 140| merge|tags: build_4445_release_10_260_success",
            "230 | BUG-333|tags: build_4444_release_10_260_success",
            "225 | BUG-666",
            "220<-120 | first commit after branch",
            "branch: origin/release/10.250",  # ---- branch
            "150 | BUG-555",
            "140 | BUG-444",
            "130 | BUG-333|tags: build_4304_release_10_250_success ",
            "120 | BUG-222|tags: build_4303_release_10_250_success",
            "110 | BUG-111",
            "15  | Initial Commit",
            name="component_1",
        )

        class Comp1Repo(ProjectRepo):
            _SAVED_BUILD_NUM_SOURCES = ["VERSION", ]

            def _read_saved_build_numbers_from_file(self, blob, path):
                data = blob.data_stream.read().decode().strip()
                nums = [int(chunk) for chunk in data.split('.')]
                if len(nums) == 2:
                    nums.append(None)
                return nums

        class DemoRepoCollection(ReposCollection):
            _REPOS_TYPES = {
                'comp_1': Comp1Repo,
            }

        cls.repos = DemoRepoCollection({
            'comp_1': Comp1Repo('comp_1', component_1_git_repo),
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
        """Verify data for 'BUG-222' report."""
        reports_data = self.repos.make_reports_data("BUG-222")
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
        """Verify data for 'BUG-333' report."""
        reports_data = self.repos.make_reports_data("BUG-333")
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
        """Verify data for 'BUG-444' report."""
        reports_data = self.repos.make_reports_data("BUG-444")
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
        """Verify data for 'BUG-555' report."""
        reports_data = self.repos.make_reports_data("BUG-555")
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
        """Verify data for 'BUG-666' report."""
        reports_data = self.repos.make_reports_data("BUG-666")
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
        """Verify data for 'BUG-777' report."""
        reports_data = self.repos.make_reports_data("BUG-777")
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
