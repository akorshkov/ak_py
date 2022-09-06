"""Test ghist module.

ghist module fetches and reports history of commits and builds for specified bug(s).
"""
import unittest
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


class _MockedGitCommit:
    # mocked git commit object
    _AUTHORS = ["V. Arnold", "Arnold Sh."]
    _BASE_TIME = random.randint(10000, 20000) * 86400

    def __init__(self, iid, parents, message, tags, repo_name):
        self.iid = iid  # integer id, should be unique within a repo
        s = f"{self.iid:05}"

        # generate hexhsa unique, repeatable and indicating iid of commit
        hs = sha1((repo_name + s).encode()).hexdigest()
        self.hexsha = hs[:1] + s[-5:] + hs[6:]
        self.parents = parents  # [_MockedGitCommit, ]
        self.message = message

        # note: actual git.commit object does not have 'tags' attribute
        self.tags = tags

        # following attributes are used for printing out results
        # and do not affect report structure.
        self.committed_date = self._BASE_TIME + self.iid * 47 + random.randint(0, 40)
        self.author = _MockedAuthor(random.choice(self._AUTHORS))

    def __str__(self):
        return f"MockedCommit({self.iid} {self.hexsha[:11]} {self.message})"


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
            commit = self._mk_commit(descr_line, prev_commit)
            assert commit.iid not in self.all_commits, (
                f"duplicate commit iid: {commit.iid}")
            self.all_commits[commit.iid] = commit
            if commit.tags is not None:
                for tag in commit.tags:
                    tag_ref_name = "refs/tags/" + tag
                    assert tag_ref_name not in self.refs, (
                        f"duplicate tag '{tag}' detected")
                    self.refs[tag_ref_name] = _MockedGitRef(tag, commit)
            prev_commit = commit

        # finalise parents of commits
        for commit in self.all_commits.values():
            for iid in commit.parents:
                assert iid in self.all_commits, (
                    f"commit #{commit.iid} has unknown parent {iid}")
            commit.parents = [
                self.all_commits[iid] for iid in commit.parents]

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

        # chunk 0: iid and parents
        id_chunks = chunks[0].split('<-', 1)
        iid = int(id_chunks[0])
        if len(id_chunks) == 2:
            parents = [int(x) for x in id_chunks[1].split(',')]
        else:
            parents = [prev_commit.iid, ] if prev_commit is not None else []

        # get other attributes
        message = None
        tags = None

        for chunk in chunks[1:]:
            if not chunk:
                # ignore empty chunk. Probably the commit_descr ends with '|' - ok
                continue
            if chunk.startswith('tags:'):
                assert tags is None, (
                    f"duplicate 'tags:' section in commit descr: {commit_descr}")
                tags = [t.strip() for t in chunk[5:].split(',')]
                continue
            # this is message
            assert message is None, (
                f"commit descr '{commit_descr} contains duplicate 'message'"
                f"sections: '{message}' and '{chunk}'")
            message = chunk

        assert message is not None, (
            f"message is not specified in commit descr: {commit_descr}")

        return _MockedGitCommit(iid, parents, message, tags, self.name)


#########################
# Test simple scenarios with a single repo

class DemoRepoCollection(ReposCollection):
    _REPOS_TYPES = {
        'comp_1': ProjectRepo,
    }


class TestRepo(unittest.TestCase):
    def test_simple(self):
        # logs_configure(5)
        component_1_git_repo = MockedGitRepo(
            "branch: origin/master",
            "50 | BUG-444",
            "40 | BUG-333|tags: build_4304_release_10_250_success ",
            "30 | BUG-222|tags: build_4303_release_10_250_success",
            "20 | BUG-111",
            "10 | Initial Commit",
            name="component_1",
        )

        repos = DemoRepoCollection({
            'comp_1': ProjectRepo('comp_1', component_1_git_repo),
        })

        # 1. no matching commits - empty report
        reports_data = repos.make_reports_data("BUG-xxx")
        self.assertEqual(1, len(reports_data))
        cmpnt_name, rgraph = reports_data[0]
        self.assertEqual("comp_1", cmpnt_name)
        # self.assertEqual(0, len(rgraph.branches), "empty report expected")
        self.assertEqual(0, len(rgraph.rcommits), "empty report expected")

        # 2. single commit matches, it is included into a build in next commit
        reports_data = repos.make_reports_data("BUG-111")

        _, rgraph = reports_data[0]
        rbranch = rgraph.branches[0]
        self.assertEqual("master", rbranch.branch_name)
        rbuilds = rbranch.get_rbuilds_list()
        self.assertEqual(1, len(rbuilds))
        rbuild = rbuilds[0]
        self.assertEqual((10, 250, 4303, 4303), rbuild.build_num.as_tuple())

        # 3. single commit matches, it is included into a build in same commit
        reports_data = repos.make_reports_data("BUG-222")
        #repos.print_prepared_reports(reports_data)

        _, rgraph = reports_data[0]
        self.assertEqual(1, len(rgraph.branches))
        rbranch = rgraph.branches[0]
        self.assertEqual("master", rbranch.branch_name)
        rbuilds = rbranch.get_rbuilds_list()
        self.assertEqual(1, len(rbuilds))
        rbuild = rbuilds[0]
        self.assertEqual((10, 250, 4303, 4303), rbuild.build_num.as_tuple())

        #repos.print_prepared_reports(reports_data)
