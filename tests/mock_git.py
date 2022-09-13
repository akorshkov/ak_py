"""Mocked git repo - to be used for testing ak.ghist module."""

import io
import random
from hashlib import sha1


#########################
# MockedGitRepo - in-memory primitive git repo.
#

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
        "Norris, Chuck", "Elieser Yudkowsky", "Stanislav Lem",
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

        # committed_date has little effect on report structure: there is
        # a cut-off period 1 day. Dates generated here should be all
        # within 1 day range so the cut-off period is not triggered.
        self.committed_date = (
            self._BASE_TIME + self.intid * 47 % 80000 + random.randint(0, 90))

        # following attributes are used for printing out results
        # and do not affect report structure.
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
            'branch: origin/master',
            '100<-20, 40| BUG-77|tags: build_4304_release_10_250_success ',
            '--> file:VERSION:10.270|',
            '--> file:DEPENDS:{"component_a": "3.5.1", "component_b": "10.7.1"}|',
            '  20<-10   | BUG-2525  |tags: build_4303_release_10_250_success',
            '40         | Some Commit',
            '10         | Initial Commit',

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
