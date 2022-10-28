"""Tool for creating commits history from several git repos."""


from datetime import datetime
import logging
from pathlib import Path
import re
import threading

from git import Repo, SymbolicReference

from ak.color import ColorFmt, ColoredText, Palette
from ak.utils import Timer, Comparable, compare_dictionaries

logger = logging.getLogger(__name__)


# if head commit of some branch is older than latest report-related
# commit by that time - consider it obsolete and do not report
_OBSOLETE_BRANCH_CUTOFF_PERIOD = 86400 * 30


# ignore a component if oldest report-related build in this component
# is older than current commit by that time.
# (this constant could have been zero - there were no report-related commits
# of this component at the time of current commit. But let's allow for
# incorrectly configured time)
_CHECK_COMPONENTS_CUTOFF_PERIOD = 86400


#########################
# RGraph - Reduced Commits Graph
#
# Graph which contains only report-related commits and preserves structure
# of commits graph in git repository

class RCommit:
    """Commit to be included into report (aka report-related commit)

    Element of RGraph - graph of report-related commits. Contains branch-independent
    information about a commit (check description of RGraph and RBuild for more
    information)

    Commit may be related to current report in several cases:
    - it explicitely mentions the report topic (like bug number)
    - commit includes bumps of sub-projects versions (if these new versions
      contain other report-related commits)
    - a build was created from this commit, this build contains some
      other commits

    RCommit object is an element of Reduced Commits Graph - structure of this
    graph is induced by structure of commits graph in original git repository.
    """
    def __init__(self, commit, parents, is_explicit, build_nums, iid=None):
        self.iid = iid
        self.commit = commit  # git.Commit
        self.parents = parents  # [RCommit, ]
        self.is_explicit = is_explicit  # commit is explicitely related to report

        # Following attributes may be not initialized in case they are not
        # required for report
        self.build_nums = build_nums  # [BuildNumData, ]
        self.build_num = build_nums[0] if build_nums else None  # smallest, if any

    def __str__(self):
        t = ""
        t += "e" if self.is_explicit else "."
        t += "b" if self.build_num else "."
        hexsha = self.commit.hexsha[:11]
        name = self.commit.author.name
        message = self.commit.message.split('\n')[0].strip()
        build_num = f" |{self.build_num}|" if self.build_num else ""
        return f"<{self.iid}: {t}: {hexsha} {name} {message}{build_num}>"

    def __repr__(self):
        return str(self)


class ComponentBump:
    """Info about change of component version in some commit.

    Note:
    1. It should always be possible to tell exactly what is the version of a
    component in our commit. But there may be more (or less) than one parent
    commits, so 'to_buildnum' can contains only one BuildNumData, but
    'from_build_nums' is a list.

    2. in order to decide if the bump of component is relevant for a report it
    is necessary to understand if the new version of component contains any
    report-related commits. So this object contains information not only about
    new and previous versions of component, but also about latest report-related
    build corresponding to these versions.
    """

    __slots__ = 'from_build_nums', 'to_buildnum', 'from_rbuilds', 'to_rbuild'

    def __init__(
            self,
            from_build_nums, to_buildnum,
            from_rbuilds, to_rbuild,
    ):
        """Construct ComponentBump - info about bump of a component version

        Arguments:
        - from_build_nums: [BuildNumData, ]
        - to_buildnum: optional BuildNumData
        - from_rbuilds: idmap of RBuild's
        - to_rbuild: optional RBuild
        """
        self.from_build_nums = from_build_nums
        self.to_buildnum = to_buildnum
        self.from_rbuilds = from_rbuilds
        self.to_rbuild = to_rbuild

    def is_trivial(self):
        """Check if this change of version component is significant for report."""
        if self.to_rbuild is None:
            if self.from_rbuilds:
                # unusual situation: this component was present in parent builds
                # but is not present in this project's repo any more
                # assert False
                return False
            return True
        return self.to_rbuild.iid in self.from_rbuilds

    def get_rbuilds_in_bump(self):
        """Get {idd: RBuild} - all RBuild's included into this bump.

        For example, this ComponentBump states that compenent version changed
        from 1.1.5 to 1.1.10 since last build. But versions 1.1.7 and 1.1.8 are
        also report-related. In this case this method will return component
        RBuild's corresponding to 1.1.5, 1.1.7 and 1.1.8. All this versions
        of component were included into the same build of parent repo.
        """
        if self.to_rbuild is None:
            return {}
        # DFS rbuilds in the component
        dfs_stack = [[self.to_rbuild]]
        dfs_sp = [0]
        result_rbuilds = {}
        while dfs_stack:
            cur_sp = dfs_sp[-1]
            if cur_sp < 0:
                # all commits on top level processed.
                # finish processing commit on previous level
                dfs_stack.pop()
                dfs_sp.pop()
                if not dfs_stack:
                    # DFS completed
                    break
                cur_sp = dfs_sp[-1]
                cur_rbuild = dfs_stack[-1][cur_sp]

                result_rbuilds[cur_rbuild.iid] = cur_rbuild
                dfs_sp[-1] = cur_sp - 1
                continue

            cur_rbuild = dfs_stack[-1][cur_sp]

            if cur_rbuild.iid in self.from_rbuilds:
                # do not go deeper
                dfs_sp[-1] = cur_sp - 1
                continue

            # need to go deeper to analize cur_commit
            parents = sorted(
                cur_rbuild.parent_rbuilds.values(),
                key=lambda rb: rb.iid)
            dfs_stack.append(parents)
            dfs_sp.append(len(parents) - 1)

        return result_rbuilds

    def __str__(self):
        is_triv = "(t) " if self.is_trivial() else ""
        to_rbuild_descr = (
            "--" if self.to_rbuild is None
            else f"{self.to_rbuild.iid}.{self.to_rbuild}"
        )
        return (
            f"bump {self.to_buildnum}{is_triv} <- {self.from_build_nums} "
            f"({to_rbuild_descr} <- {self.from_rbuilds})")

    def __repr__(self):
        return str(self)


class BranchName(Comparable):
    """Branch name with smart sorting rules."""

    __slots__ = 'name', '_sort_items'

    def __init__(self, branch_name, sort_prefix=None):
        """BranchName constructor.

        Arguments:
        - branch_name: string, for eample "origin/release/10.250"
        - sort_prefix: optional list of items, which affect sorting rules (*)

        (*) For example, branch_name "origin/release/10.250" is transformed
        to sorting items ["origin", "release", 10, 250]. If sort_prefix=["zzz"]
        is specified, sorting items will be ["zzz", "origin", "release", 10, 250]
        """
        self.name = branch_name
        self._sort_items = list(self._mk_sort_items(self.name))
        if sort_prefix is not None:
            self._sort_items = sort_prefix + self._sort_items

    @staticmethod
    def _mk_sort_items(str_val):
        # branch_name -> tuple of strings and integers (to be used for sorting):
        # "release/ABA12.5U1" -> ("release", "ABA", 12, "5U1")
        s = str_val.replace(
            '/', ' ').replace('.', ' ').replace('-', ' ').replace('_', ' ')
        chunks = s.split()
        for strvalue in chunks:
            try:
                ivalue = int(strvalue)
                yield ivalue
            except ValueError:
                yield strvalue

    def cmp(self, other) -> int:
        """Compare branch names according to sorting rules.

        Return 0 if branch names are equal, positive number if self is 'bigger'
        and negative number otherwise.
        """
        def _cmp_sort_items(item_0, item_1):
            is_int_0 = isinstance(item_0, int)
            is_int_1 = isinstance(item_1, int)
            if is_int_0 and is_int_1:
                return item_0 - item_1
            if is_int_0:  # other is not int
                return -1  # string is always bigger
            if is_int_1:  # self must be not int
                return 1
            # both are strings
            if item_0 > item_1:
                return 1
            if item_0 < item_1:
                return -1
            return 0

        for item, other_item in zip(self._sort_items, other._sort_items):
            result = _cmp_sort_items(item, other_item)
            if result != 0:
                return result

        return len(self._sort_items) - len(other._sort_items)


class BuildNumData(Comparable):
    """Information about build number.

    Purpose of objects of this class is to keep (possibly incomplete) information
    related to build number.
    """
    __slots__ = 'major', 'minor', 'patch', 'build', 'branch_str', 'version_name'

    def __init__(
            self, major, minor, patch, *,
            build=None, branch_str=None, version_name=None):
        """Construct BuildNumData.

        Arguments:
        - major, minor, patch: integers, standard parts of build number
        - build: if not specified it is considered equal to patch.
            Build numbers "10.20.30-30" and "10.20.30" are considered identical.
        - branch_str: optional name of branch from where the build was created
        - version_name: optional name of version. If specified, the build number
            would look like "C22.10-4.5.71".
        """
        self.major = major
        self.minor = minor
        self.patch = patch
        self.build = build if build is not None else self.patch
        self.branch_str = branch_str
        self.version_name = version_name

    @classmethod
    def mk_fake_not_built(cls):
        """Make predefined number for fake "not-yet-built" build."""
        return cls(8888, 8888, 8888)

    @classmethod
    def mk_fake_not_merged(cls):
        """Make predefined number for fake "not-yet-merged" build."""
        return cls(9999, 9999, 9999)

    def is_fake_not_built(self):
        """Check if build number corresponds to fake 'not-yet-built' build."""
        return all(x == 8888 for x in (self.major, self.minor, self.patch))

    def is_fake_not_merged(self):
        """Check if build number corresponds to fake 'not-yet-merged' build."""
        return all(x == 9999 for x in (self.major, self.minor, self.patch))

    def __str__(self):
        v_name = "" if self.version_name is None else f"{self.version_name}-"
        if self.patch == self.build:
            return v_name + f"{self.major}.{self.minor}.{self.patch}"
        else:
            return v_name + f"{self.major}.{self.minor}.{self.patch}-{self.build}"

    def __repr__(self):
        return self.__str__()

    def cmp(self, other):
        def _cmp_opt_ints(item_0, item_1):
            is_int_0 = isinstance(item_0, int)
            is_int_1 = isinstance(item_1, int)
            if is_int_0 and is_int_1:
                return item_0 - item_1
            if is_int_0:  # other is not int
                return -1  # None is always bigger
            if is_int_1:  # self must be not int
                return 1
            # both are None
            return 0
        r = _cmp_opt_ints(self.major, other.major)
        if r:
            return r
        r = _cmp_opt_ints(self.minor, other.minor)
        if r:
            return r
        r = _cmp_opt_ints(self.patch, other.patch)
        if r:
            return r
        r = _cmp_opt_ints(self.build, other.build)
        return r

    def is_finalized(self):
        return all(
            v is not None
            for v in [self.major, self.minor, self.patch, self.build])

    def as_tuple(self):
        return (self.major, self.minor, self.patch, self.build)


class RBuild:
    """Info about build and RCommit's included into it.

    RBuild object can be 'fake' and correspond to set of commits not
    included into any build yet.
    """
    NORMAL, FAKE_NOT_BUILT, FAKE_NOT_MERGED = 0, 1, 2

    def __init__(self, rcommit, parent_rbuilds, rcommits, bumps, *, build_type=NORMAL):
        """RBuild - elements of Reduced Commits Graph included in a build

        Arguments:
        - rcommit: RCommit from which a project was build. Can be None
            in case of fake(*) RBuild.
        - parent_rbuilds - map of parent RBuild's. Usually there is one such parent
            (the previous build), but there may be several (in different
            sub-branches)
        - rcommits: {iid: RCommit} - new RCommit's included into this build (that
            is not included into any of previous builds).
        - bumps: {cmpnt_name: ComponentBump}
        - build_type: optional, should be specified for fake(*) builds.

        (*) fake RBuild. objects correspond to sets of commits not included
        into any build yet
        """
        assert build_type in [self.NORMAL, self.FAKE_NOT_BUILT, self.FAKE_NOT_MERGED]
        if rcommit is None:
            assert build_type != self.NORMAL
        else:
            assert build_type == self.NORMAL
            # commit marked as build is included into this build
            rcommits[rcommit.iid] = rcommit

        # internal integer id. If self is normal build it
        # corresponds to some RCommit and in this case it has same iid.
        self.iid = None

        self.build_type = build_type
        if rcommit is not None:
            self.build_num = rcommit.build_num
        elif build_type == self.FAKE_NOT_MERGED:
            self.build_num = BuildNumData.mk_fake_not_merged()
        else:
            assert False
        self.rcommit = rcommit  # RCommit
        self.parent_rbuilds = parent_rbuilds  # {iid: RBuild}
        self.bumps = bumps  # {repo_id: ComponentBump}
        self.rcommits = rcommits  # {iid: RCommit} - new RCommit's in this build

        # contains info about builds of parent component where this rbuild was
        # included into.
        # populated by parent components when they are parsed
        self.included_at = []  # [(repo_id, BranchName, BuildNumData), ]

    def __str__(self):
        return f"RBuild<{self.build_num}; {len(self.rcommits)} commits>"

    def __repr__(self):
        return str(self)

    def get_printable_rcommits(self):
        """Return properly sorted list of RCommit's to be printed in report."""
        return [
            rcommit
            for rcommit in sorted(self.rcommits.values(), key=lambda c: -c.iid)
            if rcommit.is_explicit]


class RBranch:
    """Info about report-related commits in some branch"""

    __slots__ = 'branch_name', 'rheads', 'rbuilds'

    def __init__(self, branch_name, rheads, rbuilds):
        """RBranch constructor.

        Arguments:
        - branch_name: str, for example 'release/10.240'
        - rheads: [RCommit, ]. Subgraph of git commits in a branch has a single
            head. But sub-set of commits selected for report may have not a
            single head.
        - rbuilds: id-map of RBuild's - builds in this branch
        """
        self.branch_name = branch_name
        self.rheads = rheads  # [RCommit, ] - heads or reduced graph in this branch
        self.rbuilds = rbuilds  # {iid: RBuild}

    def get_latest_rbuild(self):
        if not self.rbuilds:
            return None
        return self.rbuilds[max(self.rbuilds.keys())]

    def get_rbuilds_list(self):
        """Get sorted list of RBuild's in this branch.

        RBuild's a sorted, latest is the first.
        """
        return [
            self.rbuilds[iid]
            for iid in sorted(self.rbuilds.keys(), reverse=True)]

    def __str__(self):
        return f"RBranch<{self.branch_name}>"

    def __repr__(self):
        return str(self)


class RGraph:
    """Reduced Commits Graph.

    Graph of selected commits (f.e. commits to be included into a report).
    All commits correspond to a single git.Repo.
    Structure of graph is induced by the structure of commits graph
    of the original repo.
    """
    __slots__ = (
        'repo',
        'rcommits', '_rcommits_counter',
        'brcommits', '_brcommits_counter',
        'branches',
        'bn_map', 'min_rbuild_timestamp',
    )

    class _RepoParserCache:
        # container of misc caches used during git commits graph parsing
        __slots__ = (
            'done_commits', 'visited_commits', 'selected_commits', 'prev_branches_builds',
            'builds_detector', 'branches_refs_map', 'components_versions_cache')

        def __init__(
                self, builds_detector, branches_refs_map, components_versions_cache
        ):
            self.done_commits = set()  # {hexsha} - irrelevant (with all parents)
            self.visited_commits = {}  # {hexsha: [RCommit, ]}
            self.selected_commits = {}  # {hexsha: RCommit}
            self.prev_branches_builds = {}  # {iid: RBuild}
            self.builds_detector = builds_detector
            self.branches_refs_map = branches_refs_map
            self.components_versions_cache = components_versions_cache

    class _RepoParserPerBranchCache:
        # caches relavant during parsing of a single branch
        __slots__ = 'rcommits_bparents', 'rbuilds_ancestors'

        def __init__(self):
            self.rcommits_bparents = {}  # {RCommit.iid: RBuild's idmap}
            self.rbuilds_ancestors = {}  # {RBuild.iid: RBuild's idmap}

    class _NodeAccumdat:
        # commit information accumulated while parsing of commit's graph
        __slots__ = 'commit', 'selected_explicitely', 'relevant_cmpnts', 'rc_parents'

        def __init__(self, commit, selected_explicitely, relevant_cmpnts):
            self.commit = commit  # git.commit
            self.selected_explicitely = selected_explicitely
            self.relevant_cmpnts = relevant_cmpnts  # {repo_id, }
            self.rc_parents = []

        def __str__(self):
            return f"_NodeAccumdat({self.commit}, selected: {self.selected_explicitely})"

    class _ComponentVersionsMap:
        # info about report-related versions of component repo
        __slots__ = 'bn_map', 'cutoff_ts'

        def __init__(self, bn_map, cutoff_ts):
            self.bn_map = bn_map  # {(major, minor, patch, build): (RBranch, RBuild)}
            self.cutoff_ts = cutoff_ts  # skip checks for older commits

    def __init__(self, repo, search_predicate, cmpnts_rgraphs):
        """Construct RGraph

        Arguments:
        - repo: ProjectRepo
        - search_predicate: callable, which checks if commit should
            be selected (*). Most common ctiterion is "check if commit
            message contains some text".
        - cmpnts_rgraphs: {cmpnt_name: RGraph}

        Result graph may contain not only explicitely selected by
        'search_predicate'. For example commits corresponding to builds
        may also be included into result graph.
        """
        self.repo = repo  # ProjectRepo
        self.rcommits = {}  # {iid: RCommit} - map of all RCommit's in graph
        self._rcommits_counter = 0
        self.brcommits = {}  # {iid: RBuild} - all build commits
        # RBuild are registered with the same id's as corresponding RCommit's
        # Fake RBuild do not correspond to any RCommit, so they are registered
        # with id's which would not conflict with rcommits ids
        self._brcommits_counter = 1_000_000_000

        # get release branches
        branches_data = list(self.repo.iter_release_branches())
        branches_data.sort(key=lambda item: item[2])

        self.branches = []  # [RBranch, ] - sorted, contains info about
                            # report related commits in specific branches.
                            # (Last element corresponds to 'master' branch)

        with Timer(f"init {self.repo.repo_id} repo caches", log_method=logger.debug):
            cache = self._RepoParserCache(
                self.repo.make_builds_detector(),
                self.repo.make_branch_refs_map(),
                self.repo._mk_components_versions_cache(),
            )

        components_versions_maps = {
            cmpnt_repo_id: self._ComponentVersionsMap(
                cmpnt_rgraph.bn_map,
                cmpnt_rgraph.min_rbuild_timestamp - _CHECK_COMPONENTS_CUTOFF_PERIOD)
            for cmpnt_repo_id, cmpnt_rgraph in cmpnts_rgraphs.items()
            if cmpnt_rgraph.bn_map
        }

        # info about all builds which include any of report-related commits
        self.bn_map = {}  # {(major, minor, patch, build): (RBranch, RBuild)}
        self.min_rbuild_timestamp = None

        for ref_name, branch_name, _ in branches_data:
            prev_branch = self.branches[-1] if self.branches else None
            br_head = self.repo.repo.commit(
                cache.branches_refs_map[ref_name])
            if self.min_rbuild_timestamp is not None:
                if self.min_rbuild_timestamp > (
                    br_head.committed_date + _OBSOLETE_BRANCH_CUTOFF_PERIOD
                ):
                    # looks like this branch is very old and is not relevant any more
                    continue
            with Timer(f"read branch {self.repo.repo_id} {branch_name}",
                       report_start=True, log_method=logger.debug):
                rbranch, branch_bn_map = self._read_branch(
                    branch_name, ref_name, search_predicate,
                    prev_branch,
                    components_versions_maps,
                    cache)
            self.branches.append(rbranch)
            for k, rbuild in branch_bn_map.items():
                ts = rbuild.rcommit.commit.committed_date
                self.min_rbuild_timestamp = (
                    ts if self.min_rbuild_timestamp is None
                    else min(ts, self.min_rbuild_timestamp))
                self.bn_map[k] = (rbranch, rbuild)

        self.branches = [
            br
            for br in self.branches[::-1]  # reverse, so that 'master' is first
            if br.rbuilds  # skip branches if there is nothing to report in them
        ]

        # register 'included_at' buildnumbers in components
        for my_rbranch in self.branches:
            my_rbuilds = my_rbranch.get_rbuilds_list()
            my_rbuilds.reverse()
            for cmpnt_name, cmpnt_rgraph in cmpnts_rgraphs.items():
                for my_rbuild in my_rbuilds:
                    if my_rbuild.build_num.is_fake_not_merged():
                        continue
                    cmpnt_bump = my_rbuild.bumps.get(cmpnt_name)
                    if cmpnt_bump is None:
                        continue
                    # do register my_rbuild in component's rbuilds.
                    # This means: component build was included into this
                    # build of parent (my_rbuild)
                    inculed_into = (
                        self.repo.repo_id,
                        my_rbranch.branch_name,
                        my_rbuild.rcommit.build_num,
                    )
                    for cmpnt_rbuild in cmpnt_bump.get_rbuilds_in_bump().values():
                        cmpnt_rbuild.included_at.append(inculed_into)

    def __str__(self):
        return f"RGraph of {self.repo}"

    def __repr__(self):
        return str(self)

    def get_rbranches_by_name(self):
        """RBranch'es having any report-related data: {branch_name: RBranch}."""
        return {rbranch.branch_name: rbranch for rbranch in self.branches}

    def _read_branch(
            self, branch_name, ref_name,
            search_predicate, prev_branch,
            components_versions_maps,  # {repo_id: _ComponentVersionsMap}
            repo_cache,
    ):
        # Reduce graph of git.commit corresponding to a specified branch
        # to a graph of RCommit objects - which contains only report-related
        # commits and has structure induced by original graph.
        #
        # main parsing method
        #
        # Returns
        # - RBranch
        # - bn_map: {(major, minor, patch, build) -> RBuild}

        bn_map = {}
        cur_branch_rbuilds = {}  # idmap of RBuild objects in current branch

        # caches relevant during parsing of a single branch only
        br_cache = self._RepoParserPerBranchCache()

        # ==== init DFS ======================================
        head_commit = self.repo.repo.commit(repo_cache.branches_refs_map[ref_name])

        head_relevant_components_candidates = self._get_relevant_cmpnts_names(
            head_commit.committed_date,
            components_versions_maps.keys(), components_versions_maps,
        )

        # dfs_accumdata contains data accumulated for current commit.
        # dfs_accumdata[i] corresponds to one of commits at level i-1
        # So, dfs_accumdata[0] does not correspond to any commit and will
        # contain final results of the search.
        #
        #  -- dfs_stack structure:
        #                                     commit
        #                                     commit      commit<-   commit
        #                                     commit<-    commit     commit<-
        #                    head_commit<-    commit      commit     commit
        #
        #  -- dfs_accumdata:
        #  result_accumdat   accumdat         accumdat    accumdat
        dfs_stack = [(head_commit, )]
        dfs_sp = [0]  # pointers to commits in current path in dfs_stack
        dfs_accumdata = [
            self._NodeAccumdat(None, False, head_relevant_components_candidates), ]

        # ==== DFS loop ======================================
        while dfs_stack:
            cur_sp = dfs_sp[-1]
            if cur_sp < 0:
                # all commits on top level are processed.
                # finish processing current commit on previous level
                dfs_stack.pop()
                dfs_sp.pop()
                if not dfs_stack:
                    # DFS completed.
                    assert len(dfs_accumdata) == 1  # final results of DFS
                    break
                cur_accumdat = dfs_accumdata.pop()

                cur_commit = dfs_stack[-1][dfs_sp[-1]]
                comm_hex = cur_commit.hexsha

                # ==== create RCommit's from accumdat ========
                new_rcommit, new_rbuild, buildnums, parent_rbuilds = self._mk_rcommits(
                    cur_accumdat,
                    components_versions_maps, repo_cache, br_cache,
                    is_head_commit=cur_accumdat.commit.hexsha == head_commit.hexsha,
                )
                if new_rbuild is not None:
                    logger.debug("RBuild: %s", new_rbuild)

                # ==== register RCommit in misc caches =======
                if new_rcommit is None:
                    # this commit itsef will not be included into report...
                    assert comm_hex not in repo_cache.done_commits
                    assert comm_hex not in repo_cache.visited_commits
                    assert comm_hex not in repo_cache.selected_commits
                    if not cur_accumdat.rc_parents:
                        # ... and no parents of it. Never again look into it's subgraph
                        repo_cache.done_commits.add(comm_hex)
                    else:
                        # ... but some parents are. Need to remember them
                        repo_cache.visited_commits[comm_hex] = cur_accumdat.rc_parents
                else:
                    # this commit is selected for report
                    repo_cache.selected_commits[comm_hex] = new_rcommit

                if new_rbuild is not None:
                    # collect all RBuild ancestors of a new RBuild
                    newbuild_ancestors = {}
                    for parent in new_rbuild.parent_rbuilds.values():
                        newbuild_ancestors[parent.iid] = parent
                        newbuild_ancestors.update(
                            br_cache.rbuilds_ancestors[parent.iid])
                    br_cache.rbuilds_ancestors[new_rbuild.iid] = newbuild_ancestors
                    cur_branch_rbuilds[new_rbuild.iid] = new_rbuild

                # update bn_map
                if buildnums:
                    if new_rbuild is None:
                        for rbuild in parent_rbuilds.values():
                            for bn in buildnums:
                                bn_map[bn.as_tuple()] = rbuild
                    else:
                        for bn in buildnums:
                            bn_map[bn.as_tuple()] = new_rbuild

                continue
            # process commit on top of stack
            # cases when there is already enough info about current commit, so
            # that there is no need to go deeper
            cur_commit = dfs_stack[-1][cur_sp]
            prev_accumdat = dfs_accumdata[-1]
            comm_hex = cur_commit.hexsha
            if comm_hex in repo_cache.done_commits:
                dfs_sp[-1] -= 1
                continue
            if comm_hex in repo_cache.visited_commits:
                for rc in repo_cache.visited_commits[comm_hex]:
                    if rc not in prev_accumdat.rc_parents:
                        prev_accumdat.rc_parents.append(rc)
                dfs_sp[-1] -= 1
                continue
            if comm_hex in repo_cache.selected_commits:
                if comm_hex not in prev_accumdat.rc_parents:
                    prev_accumdat.rc_parents.append(repo_cache.selected_commits[comm_hex])
                dfs_sp[-1] -= 1
                continue

            # ==== DFS - go deeper ===========================
            dfs_stack.append(cur_commit.parents)
            dfs_sp.append(len(cur_commit.parents) - 1)

            new_accumdat = self._NodeAccumdat(
                cur_commit, search_predicate(cur_commit),
                self._get_relevant_cmpnts_names(
                    cur_commit.committed_date,
                    prev_accumdat.relevant_cmpnts,
                    components_versions_maps),
            )
            dfs_accumdata.append(new_accumdat)

        # ==== end of DFS ====================================

        assert len(dfs_accumdata) == 1
        result_accumdata = dfs_accumdata.pop()
        assert result_accumdata.commit is None

        # ==== prepare fake "not-merged-yet" build info ======
        all_commits_prev_branch = {
            iid: commit
            for rbuild in prev_branch.rbuilds.values()
            for iid, commit in rbuild.rcommits.items()
        } if prev_branch is not None else {}

        all_commits_in_this_branch = {
            iid
            for rbuild in cur_branch_rbuilds.values()
            for iid in rbuild.rcommits.keys()
        }

        not_merged_rcommits = {
            iid: rcommit
            for iid, rcommit in all_commits_prev_branch.items()
            if rcommit.is_explicit and iid not in all_commits_in_this_branch
        }

        # Get info about latest build in current branch - it will be a parent build
        # for the 'not-yet-merged' fake build.
        # Usually a build may have several parent builds, but in this case
        # only one is possible.
        # If there are several parent builds (created in different sub-branches), then
        # a fake 'not-yet-built' build would have been created based on head commit of
        # the branch.
        parent_rbuilds = {}
        if cur_branch_rbuilds:
            last_rbuild_iid = max(cur_branch_rbuilds.keys())
            parent_rbuilds[last_rbuild_iid] = cur_branch_rbuilds[last_rbuild_iid]
        assert len(parent_rbuilds) <= 1

        pending_cmpnts_bumps = {}  # {cmpnt_name: fake ComponentBump which
                                   # indicates new report-related builds of
                                   # the component}
        if cur_branch_rbuilds:
            latest_rbuild = cur_branch_rbuilds[max(cur_branch_rbuilds.keys())]
            for repo_id in latest_rbuild.bumps:
                cmpnt_prev_bump = latest_rbuild.bumps[repo_id]
                cmpnt_incl_rbuild = cmpnt_prev_bump.to_rbuild
                if cmpnt_incl_rbuild is None:
                    continue
                cmpnt_incl_buildnum = cmpnt_prev_bump.to_buildnum
                cmpnt_rbranch, _ = components_versions_maps[repo_id].bn_map[
                    cmpnt_incl_rbuild.build_num.as_tuple()]
                latest_cmpnt_rbuild = cmpnt_rbranch.get_latest_rbuild()
                bump = ComponentBump(
                    [cmpnt_incl_buildnum], latest_cmpnt_rbuild.build_num,
                    {cmpnt_incl_rbuild.iid: cmpnt_incl_rbuild}, latest_cmpnt_rbuild)
                if not bump.is_trivial():
                    pending_cmpnts_bumps[repo_id] = bump

        if not_merged_rcommits or pending_cmpnts_bumps:
            rbuild = RBuild(
                None, parent_rbuilds, not_merged_rcommits, pending_cmpnts_bumps,
                build_type=RBuild.FAKE_NOT_MERGED)
            rbuild.iid = self._brcommits_counter
            self._brcommits_counter += 1
            cur_branch_rbuilds[rbuild.iid] = rbuild
        # ==== done with fake "not-merged-yet" build info ====

        branch_rcommits = RBranch(
            branch_name, result_accumdata.rc_parents, cur_branch_rbuilds)

        repo_cache.prev_branches_builds.update(br_cache.rbuilds_ancestors)

        return branch_rcommits, bn_map

    def _mk_rcommits(
            self, accumdat, components_versions_maps, repo_cache, br_cache, *,
            is_head_commit,
    ):
        # create RCommit and RBuild objects from data accumulated from
        # git commits graph (if necessary)
        #
        # Method also returns info about buildnums and parent rbuilds - may
        # be useful even if RCommit and RBuild objects are not created.

        buildnums = None
        parent_rbuilds = None

        if not (accumdat.selected_explicitely
               or accumdat.relevant_cmpnts or accumdat.rc_parents):
            # this commit is definitely not interesting for the report
            return None, None, buildnums, parent_rbuilds

        is_build_commit = repo_cache.builds_detector.is_build_commit(accumdat.commit)
        # even if the commit is build-commit, it still may be not relevant for
        # report. Check if it relevant
        if is_build_commit or is_head_commit:
            rcommits_in_build, parent_rbuilds = self._find_new_rcommits_in_build(
                accumdat.rc_parents,
                br_cache.rcommits_bparents,
                br_cache.rbuilds_ancestors,
                repo_cache.prev_branches_builds,
            )
            contains_new_commits = accumdat.selected_explicitely or rcommits_in_build
            buildnums = repo_cache.builds_detector.get_builds_numbers(accumdat.commit)
            if is_head_commit and not buildnums:
                buildnums = [BuildNumData.mk_fake_not_built(), ]
            components_bumps = self._mk_bumps_info(
                accumdat.commit, accumdat.relevant_cmpnts, parent_rbuilds,
                components_versions_maps,
                repo_cache.components_versions_cache,
            )  # {repo_id: ComponentBump}

            non_trivial_bumps_present = any(
                not bump.is_trivial()
                for bump in components_bumps.values()
            )

            # build commit is relevant for report in three cases:
            is_rbuild = (
                # 1. it contains any new report-related commits
                contains_new_commits
                # 2. it contains bumps of relevant components
                or non_trivial_bumps_present
                # 3. there are several previous relevant builds - that means
                # relevant sub-branches are now merged. Each commit included into
                # this build is included into at least one of previous builds,
                # but only this build includes all of them together.
                or len(parent_rbuilds) > 1
            )
        else:
            # this info is not included into info about not-build commits
            rcommits_in_build, parent_rbuilds = None, None
            buildnums = []
            components_bumps = None
            is_rbuild = False

        is_rcommit = accumdat.selected_explicitely or is_rbuild

        if is_rcommit:
            new_rcommit = RCommit(
                accumdat.commit, accumdat.rc_parents,
                accumdat.selected_explicitely,
                buildnums)
            new_rcommit.iid = self._rcommits_counter
            self.rcommits[new_rcommit.iid] = new_rcommit
            self._rcommits_counter += 1
        else:
            new_rcommit = None

        if is_rbuild:
            assert new_rcommit is not None
            assert buildnums is not None
            if accumdat.selected_explicitely:
                rcommits_in_build[new_rcommit.iid] = new_rcommit
            new_rbuild = RBuild(
                new_rcommit, parent_rbuilds, rcommits_in_build, components_bumps)
            new_rbuild.iid = new_rcommit.iid
            self.brcommits[new_rbuild.iid] = new_rbuild
        else:
            new_rbuild = None

        return new_rcommit, new_rbuild, buildnums, parent_rbuilds

    def _find_new_rcommits_in_build(
            self,
            heads,  # [RCommit, ] - heads of the part of RCommit's graph to analize
            rcommits_bparents,  # {RCommit.iid: {RBuild.iid: RBuild}}
            rbuilds_ancestors,  # {RBuild.iid: {RBuild.iid: RBuild}}
            prev_branches_builds,  # idmap of all RBuild's in previous branches
    ):
        # Helper method for parsing already created part of RCommit's graph.
        # Find RCommit's not included into any builds yet, and latest RBuild's
        #
        # Method returns:
        # - {RCommit.iid: RCommit}: idmap of RCommit's not included into builds yet
        # - {RBuild.iid: RBuild}: idmap of 'latest' RBuild's
        new_rcommits = {}
        head_rbuilds = {}

        _is_cur_branch_build_iid = lambda iid: (
            iid in self.brcommits and iid not in prev_branches_builds)

        # DFS on already created part of RCommit's graph
        class _FakeRootRCommit:
            def __init__(self, parents):
                self.parents = parents

        fake_root = _FakeRootRCommit(heads)
        dfs_stack = [fake_root, ]
        dfs_sp = [len(fake_root.parents) - 1, ]  # stack path pointers

        while dfs_stack:
            cur_sp = dfs_sp[-1]
            if cur_sp >= 0:
                cur_commit = dfs_stack[-1].parents[cur_sp]
                if _is_cur_branch_build_iid(cur_commit.iid):
                    # this parent is build commit itself
                    dfs_sp[-1] -= 1
                    continue
                if cur_commit.iid in rcommits_bparents:
                    # we already know build parents of this commit
                    dfs_sp[-1] -= 1
                    continue
                # still not enough info about cur_commit. Need to analize parents
                dfs_stack.append(cur_commit)
                dfs_sp.append(len(cur_commit.parents) - 1)
                continue

            # done processing parents of some rcommit. Analyse this commit itself
            assert cur_sp < 0

            dfs_sp.pop()
            cur_commit = dfs_stack.pop()

            def _iter_parent_rbuilds():
                # get all parent RBuild's of all parent commits of cur_commit
                for parent in cur_commit.parents:
                    # every parent of cur_commit is either a build commit, or
                    # a usual commit (whose build parents we already know)
                    if _is_cur_branch_build_iid(parent.iid):
                        yield self.brcommits[parent.iid]
                    else:
                        assert parent.iid in rcommits_bparents
                        for rbuild in rcommits_bparents[parent.iid].values():
                            yield rbuild

            parent_rbuilds = {rbuild.iid: rbuild for rbuild in _iter_parent_rbuilds()}

            # parent_rbuilds may contain unnecessary items. Some build commits
            # may be already included into other build commits
            while True:
                extra_bcs = {
                    iid
                    for iid in parent_rbuilds.keys()
                    if any(
                        iid in rbuilds_ancestors[bc_iid]
                        for bc_iid in parent_rbuilds.keys()
                    )
                }
                if not extra_bcs:
                    break
                for iid in extra_bcs:
                    parent_rbuilds.pop(iid)

            # final minor optimisation: reuse map object if possible
            for parent in cur_commit.parents:
                if parent.iid in rcommits_bparents:
                    if parent_rbuilds == rcommits_bparents[parent.iid]:
                        parent_rbuilds = rcommits_bparents[parent.iid]
                        break

            if dfs_stack:
                # this is not a fake root yet
                rcommits_bparents[cur_commit.iid] = parent_rbuilds
                if cur_commit.is_explicit:
                    # otherwise cur_commit is included in RGraph only because it
                    # to a build from previous branch. There is no need to report
                    # this commit in builds of current branch
                    new_rcommits[cur_commit.iid] = cur_commit
            else:
                assert isinstance(cur_commit, _FakeRootRCommit)
                head_rbuilds = parent_rbuilds

        return new_rcommits, head_rbuilds

    def _mk_bumps_info(
            self, commit, relevant_components, parent_rbuilds,
            components_versions_maps,
            components_versions_cache,
    ):
        # Returns {repo_id: ComponentBump} - info about report-related bumps
        # of components since previous report related build(s) of current repo

        cur_components_buildnums = self._get_relevant_cmpnts_versions(
            commit, relevant_components,
            components_versions_maps,
            components_versions_cache,
        )  # {repo_id: BuildNumData}

        components_bumps = {}  # {repo_id: ComponentBump}
        for repo_id, cur_component_bn in cur_components_buildnums.items():
            if repo_id not in relevant_components:
                continue

            cur_component_rbuild = None
            if cur_component_bn is not None:
                cmpnt_bn_map = components_versions_maps[repo_id].bn_map
                branch_and_build = cmpnt_bn_map.get(
                    cur_component_bn.as_tuple(), None)
                if branch_and_build is not None:
                    cur_component_rbuild = branch_and_build[1]

            from_builnums = []
            from_rbuilds = {}
            for parent_rbuild in parent_rbuilds.values():
                parent_component_bump = parent_rbuild.bumps.get(repo_id)
                if not parent_component_bump:
                    continue
                from_builnums.append(parent_component_bump.to_buildnum)
                if parent_component_bump.to_rbuild is not None:
                    prev_rbuild = parent_component_bump.to_rbuild
                    from_rbuilds[prev_rbuild.iid] = prev_rbuild
                else:
                    from_rbuilds.update(parent_component_bump.from_rbuilds)

            if cur_component_rbuild is None and from_rbuilds:
                # quite unusual situation: current commit references missing version
                # component. We do not know where this version of component was built
                # from. Let's ignore this version and act as if component version
                # have not changed
                logger.warning(
                    "repo '%s' commit '%s' references unknown version '%s' "
                    "of component '%s'",
                    self.repo.repo_id,
                    commit.hexsha[:11],
                    str(cur_component_bn),
                    repo_id,
                )
                rbuild_id = max(rb.iid for rb in from_rbuilds.values())
                cur_component_rbuild = from_rbuilds[rbuild_id]

            components_bumps[repo_id] = ComponentBump(
                from_builnums, cur_component_bn,
                from_rbuilds, cur_component_rbuild)

        return components_bumps

    def _get_relevant_cmpnts_names(
            self, commit_ts, components_to_check,
            components_versions_maps,  # {repo_id: _ComponentVersionsMap}
    ):
        # get set of names of components which still may be relevant for report
        # (the deeper we go in commit tree the less relevant components remain.
        # Component becomes irrelevant when the earliest rbuild in this
        # component becomes younger than current commit)
        return {
            repo_id
            for repo_id in components_to_check
            if commit_ts > components_versions_maps[repo_id].cutoff_ts
        }

    def _get_relevant_cmpnts_versions(
            self, commit, components_to_check,
            components_versions_maps,  # {repo_id: _ComponentVersionsMap}
            cache,
    ):
        # return {comp_name: optional BuildNumData} for components still
        # relevant for report
        # (component is irrelevant if we are sure that earlier commits do not
        # contain any report-related builds of this component)
        #
        # Note: method may return versions of components not included
        # into components_to_check.
        ret_val = {}
        commit_components_versions = self.repo.get_components_versions(
            commit, components_to_check, cache)
        for comp_name, build_num in commit_components_versions.items():
            if comp_name not in components_versions_maps:
                # repo returned info about some component, but we do not
                # care about this component for some reason
                continue
            cmpnt_vmap = components_versions_maps[comp_name]
            if commit.committed_date < cmpnt_vmap.cutoff_ts:
                continue

            ret_val[comp_name] = build_num

            # not found rbuild usually means that specified version of component
            # does not contain any report-related commits, so it is possible
            # to skip rest of the graph.
            # But it can be wrong in several rare cases (if component version numbers
            # do not grow monotonously in parent repo) - so instead of not reporting
            # this component at all report None ('not found') version
        return ret_val


class GitRepo(Repo):
    """git.Repo with some addtional features."""

    def __init__(self, repo_path):
        """Constructor of GitRepo: git.Repo with a few additional features."""
        super().__init__(repo_path)

    def iter_refs(self, *prefixes):
        """yields (ref_name, optional_hexsha) for all refs having specified prefixes.

        Finding commit associated with ref_obj is very inefficient in GitPython.
        This method can be used to find commits corresponding to a number of
        refs in one run.

        If the yielded optional_hexsha value is None, correct hexsha can be found
        the following way:
        hexsha = SymbolicReference(repo, ref_name).commit.hexsha

        (info about ref can be stored in .git either in one of two locations:
        1. packed-refs file. GitPython is inefficient in this case, but this method
            yields correct hexsha
        2. separate file. This method yileds None in this case, but GitPython can
            be used to get correct value.

        Yielded ref_name's are full, for example:
        - 'refs/remotes/origin/release/abc-7.5'
        - 'refs/tags/build_1128_release_9_60_success'
        """
        for prefix in prefixes:
            assert prefix.startswith("refs/")

        # remove redundant prefixes
        if prefixes:
            prefixes = sorted(prefixes)
            unique_prefixes = [prefixes[0]]
            for p in prefixes[1:]:
                if not p.startswith(unique_prefixes[-1]):
                    unique_prefixes.append(p)
            prefixes = unique_prefixes

        # iter refs on file-system
        fs_ref_names = set()
        for prefix in prefixes:
            for ref_name, _path in self._iter_refs_files(prefix):
                fs_ref_names.add(ref_name)
                yield ref_name, None

        # iter packed-refs
        for ref_name, hexsha in self._iter_packed_refs(prefixes):
            if ref_name in fs_ref_names:
                # packed-refs contains incorrect values of hexsha in case
                # there is a ref file on file-system.
                # do not report such invalid values
                continue
            yield ref_name, hexsha

    def _iter_packed_refs(self, prefixes):
        # yield (ref_name, hexsha) for refs stored in '.git/packed-refs'
        #
        # Note, that haxsha values stored in the packed-refs may be 'incorrect'
        # In case there is a ref file in '.git/refs/...' that file contains
        # correct hexsha value
        if isinstance(prefixes, str):
            prefixes = [prefixes, ]
        packed_refs_path = Path(self.git_dir) / "packed-refs"
        accum_ref_name, accum_hexsha = None, None
        try:
            with open(packed_refs_path) as refs_file:
                for line in refs_file:
                    line = line.strip()
                    if not line:
                        continue
                    if line[0] == '#':
                        # expected very first line to be a comment like this
                        # '# pack-refs with: peeled fully-peeled sorted'
                        if any(s not in line for s in ['# pack-refs', 'peeled']):
                            raise TypeError(
                                f"PackingType of packed-Refs not understood: '{line}'")
                        continue
                    if line[0] == '^':
                        # lines like these in the file mean
                        # fc6e...62 refs/tags/some_tag <- hexsha of tag object
                        # ^27d4...9f                   <- hexsha of the tagged commit
                        # we need to report the hexsha of actual commit
                        if len(line) != 41:
                            raise TypeError(
                                f"unexpected line '{line}' in {packed_refs_path}")
                        if accum_hexsha:
                            accum_hexsha = line[1:]
                        continue
                    hexsha, ref_name = line.split(None, 1)

                    if accum_hexsha:
                        yield accum_ref_name, accum_hexsha
                        accum_ref_name, accum_hexsha = None, None

                    if any(ref_name.startswith(prefix) for prefix in prefixes):
                        accum_ref_name, accum_hexsha = ref_name, hexsha
            if accum_hexsha:
                yield accum_ref_name, accum_hexsha
        except OSError:
            logger.warning("Can't process %s", packed_refs_path)

    def _iter_refs_files(self, prefix):
        # yield (ref_name, path) for refs stored in '.git/refs/' dir of git storage
        git_dir = Path(self.git_dir)
        refs_dir = Path(self.git_dir) / prefix
        for f in refs_dir.glob("**/*"):
            if not f.is_file():
                continue
            ref_name = str(f.relative_to(git_dir))
            yield ref_name, f

    def get_ref_commit(self, ref_name):
        """Get commit corresponding to reference.

        Arguments:
        - ref_name: string, full ref name, f.e. "refs/remote/origin/master"
        """
        return SymbolicReference(self, ref_name).commit


class ProjectRepo:
    """Provides access to a single git repository of some project.

    Implementation of some operations (like finding out sub-component version
    corresponding to a specific commit) is project-specific. It is supposed that
    this functionality will be implemented in derived classes - so in most cases
    there will be a separate ProjectRepo-derived class for each project.
    """

    REPO_DESCR = None  # optional description of repository

    # successfull build tag examples:
    #   build_4155_master_success
    #   build_4154_release_10_240_success
    _RE_BUILD_TAG = re.compile(
        r"build_(?P<build>\d+)_(?P<branch>.*)_success$"
    )

    # release branch name in successfull build tag
    #   release_10_250
    _RE_BRANCH_IN_TAG_SUBSTR = re.compile(
        r"release_(?P<major>\d+)_(?P<minor>\d+)$"
    )

    # list of possible locations of a file, which contains version number
    # of this component. Usually it is a 'VERSION' or some '__init__.py' file.
    # Check doc of get_saved_build_number method for more details
    _SAVED_BUILD_NUM_SOURCES = []  # list of strings - paths to files

    # locations of files which contain verstions of sub-components
    _COMPONENTS_VERSIONS_LOCATIONS = {}  # {project_repo_id: local_path}

    __slots__ = 'repo_id', 'repo', 'remote_name'

    def __init__(self, repo_id, repo_path, remote_name):
        """ProjectRepo constructor.

        Arguments:
        - repo_id: string, repo_id of this ProjectRepo.
        - repo_path: path to local git repository or GitRepo object
        - remote_name: name of the git remote. Local data fetched from this
            remote will be used for report.
        """
        self.repo_id = repo_id
        self.repo = repo_path if hasattr(repo_path, 'remotes') else GitRepo(repo_path)
        assert remote_name, (
            "Remote name must be specified. Preparing reports for commits "
            "not pushed to remote server is not supported yet.")
        self.remote_name = remote_name

    def __str__(self):
        return f"ProjectRepo {self.repo_id} ({type(self)})"

    def __repr__(self):
        return str(self)

    def build_report_rgraph(self, search_text, components_rgraphs):
        """Prepare and return RGraph

        RGraph - graph of RCommit's - commits which are related to
        current report.

        Arguments:
        - search_text: string to find in commit messages
        - components_rgraphs: {cmpnt_name: RGraph} - report-related commits
        of components.
        """
        # ToDo: make it an option
        #search_predicate = lambda commit: search_text in commit.message.split('\n')[0]
        search_predicate = lambda commit: search_text in commit.message

        with Timer(f"search '{search_text}' '{self.repo}' repo", log_method=logger.info):
            gr = RGraph(self, search_predicate, components_rgraphs)

        return gr

    def sync(self) -> bool:
        """Sync with remote: 'git fetch <remote_name>'

        Return value indicates if sync was successfull.
        """
        with Timer(
            f"sync {self.repo_id} {self.repo.working_dir} {self.remote_name}",
            report_start=True,
            log_method=logger.info
        ):
            remote = self.repo.remotes[self.remote_name]
            try:
                remote.fetch()
            except:
                logger.exception(
                    "Unexpected error during Repo '%s' synchronization", self.repo)
                return False
        return True

    def iter_release_branches(self):
        # yield (ref_name, branch_name, BranchName) for release branches
        prefix_len = len(f"{self.remote_name}/")
        for ref in self.repo.remotes[self.remote_name].refs:
            if ref.name in (f"{self.remote_name}/master", f"{self.remote_name}/main"):
                bn = BranchName(ref.name, sort_prefix=["zzzzzzzzzzzzzz", ])
                branch_name = ref.name[prefix_len:]
                yield ref.name, "master", bn
            if ref.name.startswith(f"{self.remote_name}/release/"):
                branch_name = ref.name[prefix_len:]
                bn = BranchName(ref.name)
                yield ref.name, branch_name, bn

    def _read_saved_build_num_from_file(self, blob, path) -> BuildNumData:
        # to be implemented in derived classes if necessry
        #
        # applicable for repositories where build number is stored in a file
        _ = blob, path
        raise NotImplementedError(f"Implement this method in '{type(self)}'!")

    #########################
    # methods for processing info about builds associated with commits

    def make_builds_detector(self):
        """Make RepoBuildsDetector - object which gets builds info from repo"""
        # default implementation guess build numbers by git tags.
        # in order for it to work derived ProjectRepo class should implement
        # several project-specific methods (check RepoBuildsByTagDetector doc)
        return RepoBuildsByTagDetector(self)

    @classmethod
    def parse_buildtag(cls, tag_str) -> BuildNumData:
        """tag_str -> BuildNumData (if tag_str is a build tag)."""
        return cls._parse_default_buildtag(tag_str)

    @classmethod
    def _parse_default_buildtag(cls, tag_str):
        # match tag to successfull build tag pattern in 'standard' format
        m = cls._RE_BUILD_TAG.match(tag_str)
        if m is None:
            return None

        return BuildNumData(
            None, None, None, # major, minor, patch
            build=int(m.group('build')),
            branch_str=m.group('branch'),
        )

    def guess_major_minor_build_by_tag_substr(self, tag_substr):
        """'release_10_240' -> (10, 240)"""
        # this method is required if RepoBuildsByTagDetector by this repo.
        # default implementation, works if standard build tags (like
        # 'build_4154_release_10_240_success') are used
        m = self._RE_BRANCH_IN_TAG_SUBSTR.match(tag_substr)
        if m:
            return int(m.group('major')), int(m.group('minor'))
        return None, None

    def get_saved_build_number(self, commit, cache) -> BuildNumData:
        """Get build number info saved in a file in commit.

        Returns BuildNumData. It should be treated not as an actual build number
        but as a container of known attributes.

        Returned build number is NOT a build number this commit is included into.
        If build number if saved in component source files, than build is triggered
        when this saved number changes. For example several commits contain build
        number 1.1.1, then new commit increases this version to 1.1.2 and build is
        triggered. Artifact version will be 1.1.2, but it will contain only one
        commit with version 1.1.2. All subsequent commits with this version will
        be included into build 1.1.3 only.
        """
        # default implementation tries to read major-minor-patch from
        # files specified in _SAVED_BUILD_NUM_SOURCES
        try:
            return cache[commit.hexsha]
        except KeyError:
            pass

        problems_descrs = []

        for local_path in self._SAVED_BUILD_NUM_SOURCES:
            try:
                blob = commit.tree / local_path
            except KeyError as err:
                problems_descrs.append(str(err))
                continue

            if blob.hexsha in cache:
                build_num = cache[blob.hexsha]
                cache[commit.hexsha] = build_num
                return build_num

            try:
                build_num = self._read_saved_build_num_from_file(
                    blob, local_path)
            except ValueError as err:
                problems_descrs.append(str(err))
                continue

            cache[blob.hexsha] = build_num
            cache[commit.hexsha] = build_num

            return build_num

        # failed to read build info from any sources
        logger.debug(
            "failed to read build info from commit '%s': %s",
            commit.hexsha,
            "; ".join(
                f"{local_path}: {err}"
                for local_path, err in zip(
                    self._SAVED_BUILD_NUM_SOURCES, problems_descrs)
            ))
        major, minor, patch = ('?', '?', '?')
        build_num = BuildNumData(major, minor, patch)
        cache[commit.hexsha] = build_num
        return build_num

    #########################
    # methods for processing components versions

    def get_components_versions(self, commit, components, cache):
        """Get info avout versions of specified components.

        Arguments:
        - commit: git.commit object
        - components: list of names of components to get versions of.
            If is None - version of all known components will wi returned

        Return value:
        - {component_name: BuildNumData}: - may contain info about not
            requested components
        """
        if components is None:
            # get info about all components if components not specified
            components = self._COMPONENTS_VERSIONS_LOCATIONS.keys()

        assert all(c in self._COMPONENTS_VERSIONS_LOCATIONS for c in components)
        known_componens = cache.get(commit.hexsha, {})
        components_to_check = {}
        for c in components:
            if c not in known_componens:
                v_file_path = self._COMPONENTS_VERSIONS_LOCATIONS[c]
                components_to_check.setdefault(v_file_path, []).append(c)

        if not components_to_check:
            return known_componens

        for v_file_path, cmps in components_to_check.items():
            try:
                blob = commit.tree / v_file_path
            except KeyError:
                logger.warning(
                    "repo '%s' commit '%s' does not contain a file '%s'",
                    self.repo.name,
                    commit.hexsha[:11],
                    v_file_path,
                )
                continue

            try:
                components_in_file = cache[blob.hexsha]
            except KeyError:
                components_in_file = {
                    cmpnt: BuildNumData(major, minor, patch)
                    for cmpnt, (major, minor, patch)
                    in self.read_components_from_file(v_file_path, blob).items()
                }
                cache[blob.hexsha] = components_in_file

            missing_components = [c for c in cmps if c not in components_in_file]
            assert not missing_components, (
                f"info about versions of components {missing_components} not "
                f"found in file '{v_file_path}'. Check implementation of "
                f"method 'read_components_from_file' in {type(self)}")

            known_componens.update(components_in_file)

        cache[commit.hexsha] = known_componens
        return known_componens

    def read_components_from_file(self, v_file_path, blob):
        # to be implemented in derived classes
        # should return {'component_name': (major, minor, patch)}
        _ = v_file_path
        _ = blob
        return {}

    #########################
    # some ProjectRepo utils

    def _mk_components_versions_cache(self):
        # ovride in derived class if simple dictionary is not enough
        return {}

    def make_branch_refs_map(self, remote_name=None):
        """Make {ref_name: commit.hexsha} for branches in specified remote.

        Arguments:
        - remote_name: (optional) string, name of remote

        ref_name in result dictionary contains remote name, for example:
        'origin/release/10.240'
        This is consistent with GitPython lib behavior:
        repo.remotes['origin'].refs['master'].name == "origin/master"
        """
        if remote_name is None:
            remote_name = self.remote_name
        assert remote_name, "local branches not supported yet"
        refs_map = {}
        ref_prefix = f"refs/remotes/{remote_name}/"
        chop_off_len = len("refs/remotes/")
        for ref_full_name, hexsha in self.repo.iter_refs(ref_prefix):
            ref_name = ref_full_name[chop_off_len:]
            if hexsha is None:
                hexsha = self.repo.get_ref_commit(ref_full_name).hexsha
            refs_map[ref_name] = hexsha
        return refs_map

    def make_buildtags_map(self):
        """Make {commit.hexsha: [BuildNumData, ]} of successfull builds"""
        builds_map = {}
        prefix = "refs/tags/"
        prefix_len = len(prefix)
        for ref_name, hexsha in self.repo.iter_refs(prefix):
            tag_str = ref_name[prefix_len:]
            t = self.parse_buildtag(tag_str)
            if t:
                if hexsha is None:
                    hexsha = self.repo.get_ref_commit(ref_name).hexsha
                builds_map.setdefault(hexsha, []).append(t)
        return builds_map

    def _test_iter_tags(self):
        # For test purposes only.
        # Refs iterator accesses refs information directly from .git storage
        # Make sure that tags info created with refs iterator are cated correctly.

        with Timer("get tags hexsha old"):
            _ = self.make_buildtags_map()

        tags_map_direct = {}
        with Timer("get tags from .git directly"):
            for ref_name, hexsha in self.repo.iter_refs("refs/tags/"):
                tag_str = ref_name[len("refs/tags/"):]
                if hexsha is None:
                    hexsha = self.repo.get_ref_commit(ref_name).hexsha
                tags_map_direct[tag_str] = hexsha

        with Timer("get tags using git package"):
            tags_map_gitlib = {
                tag.name: tag.commit.hexsha
                for tag in self.repo.tags
            }

        compare_dictionaries(
            tags_map_direct, "directly collected tags",
            tags_map_gitlib, "collected with lib tags",
        )

    def _test_iter_branchrefs(self):
        # For test purposes only.
        # Refs iterator accesses refs information directly from .git storage
        # Make sure that branch refs created with ref iterator are created correctly.

        with Timer("get refs using direct access"):
            dummy_d = self.make_branch_refs_map(self.remote_name)

        with Timer("get refs using git package"):
            refs_gitlib = {
                ref.name: ref.commit.hexsha
                for ref in self.repo.remotes[self.remote_name].refs
            }

        compare_dictionaries(
            dummy_d, "direct",
            refs_gitlib, "refs_gitlib",
        )


class RepoBuildsDetector:
    """Base class for build commit detectors objects.

    Procedure of finding out if some commit corresponds to a build depends
    on repo (note, that in some repos it is even impossible).
    Objects of RepoBuildsDetector implement build-number-related procedures
    and keep caches.
    """
    def is_build_commit(self, commit) -> bool:
        """Check if some successful build was based on this commit."""
        _ = commit
        assert False, "Not implemented"

    def get_builds_numbers(self, commit):
        """commit -> [BuildNumData, ] for builds based on this commit.

        Returned list is sorted in ascending order.
        """
        _ = commit
        assert False, "Not implemented"


class RepoBuildsByTagDetector(RepoBuildsDetector):
    """Detector of a build commits in a repo.

    Build commit are detected by tags.
    """
    def __init__(self, project_repo):
        """RepoBuildsByTagDetector constructor.

        Arguments:
        - project_repo: ProjectRepo object. This ProjectRepo must implement
            following methods:
            - guess_major_minor_build_by_tag_substr
            - get_saved_build_number
        """
        self.project_repo = project_repo
        self.buildtags_map = project_repo.make_buildtags_map()
        self.cache = {}

    def is_build_commit(self, commit):
        """Check if some successful build was based on this commit."""
        return commit.hexsha in self.buildtags_map

    def get_builds_numbers(self, commit):
        """commit -> [BuildNumData, ] for builds based on this commit."""
        parsed_bts = self.buildtags_map.get(commit.hexsha, [])
        for bt in parsed_bts:
            self.finalize_build_tag_info(bt, commit)
        parsed_bts.sort()
        return parsed_bts

    def finalize_build_tag_info(self, parsed_bt, commit):
        """Fill missing attributes of parsed_bt

        Arguments:
        - parsed_bt: BuildNumData
        - commit: git.commit
        - cache: dictionary (it's up to this method what to keep in it)
        """
        assert parsed_bt.build is not None
        if all(v is not None for v in [parsed_bt.major, parsed_bt.minor]):
            if parsed_bt.patch is None:
                parsed_bt.patch = parsed_bt.build
            return
        # try to guess major.minor by tag
        major, minor = self.project_repo.guess_major_minor_build_by_tag_substr(
            parsed_bt.branch_str)
        if major is not None:
            parsed_bt.major = major
            parsed_bt.minor = minor
            if parsed_bt.patch is None:
                parsed_bt.patch = parsed_bt.build
            return
        # need to get build numbers from files
        try:
            fs_buildnum_data = self.project_repo.get_saved_build_number(
                commit, self.cache)
        except ValueError as err:
            raise ValueError(
                f"Repo: {self.project_repo.repo_id}: can't get build number from "
                f"commit '{commit.hexsha}'."
            ) from err

        parsed_bt.major = fs_buildnum_data.major
        parsed_bt.minor = fs_buildnum_data.minor
        if parsed_bt.patch is None:
            parsed_bt.patch = parsed_bt.build
        assert parsed_bt.is_finalized(), f"'{parsed_bt}' is not finalized"


class RepoBuildsBySavedBuildNumDetector(RepoBuildsDetector):
    """Detect build commit by info saved in a file.

    For example version is saved in a file 'current_version' in simple
    text like '10.250.43'. Usually new build is created when this version is
    bumped. It may be not true sometimes, but this is best guess we can do.

    In order to use this detector the project repo must implement
    get_saved_build_number method (or specify _SAVED_BUILD_NUM_SOURCES and
    implement _read_saved_build_num_from_file method).
    """
    def __init__(self, project_repo):
        self.project_repo = project_repo
        self.cache = {}

    def is_build_commit(self, commit) -> bool:
        """Check if build was created from this commit."""
        cur_saved_build_num = self.get_builds_numbers(commit)[0]
        return all(
            cur_saved_build_num != self.get_builds_numbers(c)[0]
            for c in commit.parents
        )

    def get_builds_numbers(self, commit):

        # there is only one
        return [self.project_repo.get_saved_build_number(commit, self.cache), ]


class ReposCollection:
    """Collection of ProjectRepo's."""

    _REPOS_TYPES = {}  # {repo_id: ProjectRepo-class}

    def __init__(self, repos):
        """Construct ReposCollection - all git repos to use for report.

        Arguments:
        - repos: {repo_id: project_repo_description(*) ProjectRepo or path to repo}

        (*) project_repo_description may be in followinf formats:
        - "path/to/git/repo"
        - ProjectRepo object
        - ("path/to/git/repo", "remote_name")
        - (ProjectRepo object, "remote_name")

        Default remote_name is "origin"

        In case path to git repo is specified, ProjectRepo objects will be
        constructed, actual types of the objects will be taken from _REPOS_TYPES
        """
        self.repos = {}
        for repo_id, repo_info in repos.items():
            if isinstance(repo_info, (list, tuple)):
                repo_info, remote_name = repo_info
                if remote_name is None:
                    remote_name = 'origin'
            else:
                remote_name = 'origin'
            repo = self._mk_repo_obj(repo_id, repo_info, remote_name)
            if repo is None:
                continue
            self.repos[repo_id] = repo

        # repo ids sorted in a way that components go before owners
        self.sorted_repos = []
        done_repos = set()

        dfs_stack, dfs_sp, dfs_path_names = [], [], []
        repos_list = sorted(repo_id for repo_id in self.repos)
        if repos_list:
            dfs_stack.append(repos_list)
            dfs_sp.append(len(repos_list) - 1)
            dfs_path_names.append(repos_list[-1])

        while dfs_stack:
            cur_sp = dfs_sp[-1]
            if cur_sp < 0:
                dfs_stack.pop()
                dfs_sp.pop()
                dfs_path_names.pop()
                continue
            cur_repo_id = dfs_stack[-1][cur_sp]
            if cur_repo_id in done_repos:
                cur_sp = dfs_sp[-1] - 1
                dfs_sp[-1] = cur_sp
                dfs_path_names[-1] = dfs_stack[-1][cur_sp] if cur_sp >= 0 else None
                continue
            cur_repo = self.repos[cur_repo_id]
            not_processed_sub_components = sorted(
                repo_id
                for repo_id in cur_repo._COMPONENTS_VERSIONS_LOCATIONS
                if repo_id in self.repos and repo_id not in done_repos)

            if not not_processed_sub_components:
                # all dependecies are processed, finalise this repo
                self.sorted_repos.append(cur_repo_id)
                done_repos.add(cur_repo_id)
                cur_sp = dfs_sp[-1] - 1
                dfs_sp[-1] = cur_sp
                dfs_path_names[-1] = dfs_stack[-1][cur_sp] if cur_sp >= 0 else None
                continue

            # detect cycle dependencies
            cycled_repo_ids = [
                repo_id
                for repo_id in not_processed_sub_components
                if repo_id in dfs_path_names]
            if cycled_repo_ids:
                bad_repo = cycled_repo_ids[0]
                i = dfs_path_names.index(bad_repo)
                cycle = dfs_path_names[i:]
                cycle.append(bad_repo)
                assert len(cycle) > 1
                assert cycle[0] == cycle[-1]
                raise ValueError(
                    "repo dependencies cycle detected: " + " -> ".join(cycle))

            # some dependencies are not processed yet, go deeper in dfs
            dfs_stack.append(not_processed_sub_components)
            dfs_sp.append(len(not_processed_sub_components) - 1)
            dfs_path_names.append(not_processed_sub_components[-1])

        assert len(self.sorted_repos) == len(self.repos)

    @classmethod
    def _mk_repo_obj(cls, repo_id, repo_address, remote_name):
        # helper to be used in constructor. Creates ProjectRepo
        #
        # Arguments:
        # - repo_id: string
        # - repo_address: either path to git reporitory or a ready ProjectRepo

        if hasattr(repo_address, 'build_report_rgraph'):
            # repo_address is a redy repo project
            return repo_address
        try:
            repo_class = cls._REPOS_TYPES[repo_id]
        except KeyError:
            logger.warning("unknown repo type '%s' encountered", repo_id)
            return None
        return repo_class(repo_id, repo_address, remote_name)

    def sync(self):
        """Sync all the repos in the collection.

        Method returns (num_synced, num_failed)
        """
        results = {}  # {repo_id: if_sync_successfull}

        def run_job(repo_id):
            results[repo_id] = self.repos[repo_id].sync()

        threads = [
            threading.Thread(target=run_job, args=((repo_id, )))
            for repo_id in sorted(self.repos.keys())
        ]
        with Timer("total sync", log_method=logger.info):
            for th in threads:
                th.start()

            for th in threads:
                th.join()

        assert len(results) == len(self.repos)
        num_synced = sum(1 for result in results.values() if result)
        num_failed = len(results) - num_synced
        return num_synced, num_failed

    def make_reports_data(self, bug_id):
        """Prepare report of commits with descriptions contaning specified text.

        Return: [('repo_id', RGraph), ]
        """
        results = []  # [(repo_id, RGraph), ]
        rgraph_by_name = {}  # {repo_id: RGraph}

        for repo_id in self.sorted_repos:
            repo = self.repos[repo_id]
            components = {
                repo_id: rgraph
                for repo_id, rgraph in rgraph_by_name.items()
                if repo_id in repo._COMPONENTS_VERSIONS_LOCATIONS
            }
            x = repo.build_report_rgraph(bug_id, components)
            results.append((repo_id, x))
            rgraph_by_name[repo_id] = x
        results.reverse()
        return results

    def print_prepared_reports(self, report_data, color_stdout=True):
        rp = ReportPrinter(color_stdout)
        for line in rp.gen_report(report_data):
            print(line)


class ReportPrinter:
    """Pretty-print report data produced by ReposCollection.make_reports_data"""

    def __init__(self, color_stdout):
        self.palette = Palette({}) if not color_stdout else Palette({
            'REPO': ColorFmt('CYAN', bold=True),
            'BRANCH': ColorFmt('GREEN', bold=True),
            'HASH': ColorFmt('YELLOW'),
            'HASH_NOT_MERGED': ColorFmt(None),
            'COMMIT_TIME': ColorFmt('BLUE'),
            'COMMIT_NAME': ColorFmt('GREEN'),
            'VERSION': ColorFmt('CYAN'),
            'VER_NOT_BUILT': ColorFmt('RED'),
            'VER_NOT_MERGED': ColorFmt('RED'),
        })

    def gen_report(self, report_data):
        """Generate report lines for collected report data.

        Arguments:
        - report_data: [('component_name', RGraph), ] - properly ordered
            list as generated by ReposCollection.make_reports_data.
        """
        for repo_id, rgraph in report_data:
            branches = rgraph.branches
            yield ""
            yield ColoredText("==== repo ") + self.palette['REPO'](repo_id) + " ===="
            for rbranch in branches:
                yield from self._gen_branch_report(repo_id, rbranch, 0)

    def _gen_branch_report(self, repo_id, rbranch, offset):
        yield (
            self._mk_offset(offset) +
            self.palette['REPO'](repo_id) + " " +
            self.palette['BRANCH'](rbranch.branch_name) + ":")
        for rbuild in rbranch.get_rbuilds_list():
            yield from self._gen_rbuild_descr(rbuild, offset+1)

    def _gen_rbuild_descr(self, rbuild, offset):
        # generate ColoredText lines of description of RBuild (including
        # commits in this build)

        # prepare build title line
        build_title = (
            self._mk_offset(offset) + self._mk_buildnum_descr(rbuild.build_num))
        commits_merged = not rbuild.build_num.is_fake_not_merged()

        if rbuild.rcommit is not None:
            commit = rbuild.rcommit.commit
            t_time = datetime.fromtimestamp(commit.committed_date).isoformat(sep=' ')
            build_title += f" ({t_time})"

        # build_title now looks like:
        #   10.260.2714 (2022-08-31 17:36:46)
        #
        # In case 'included_at' is not empty, it's first line also goes to title line:
        #   10.260.2714 (2022-08-31 17:36:46) / parent_repo relese/3.4 10.15.35
        incl_at_offset_str = None
        if rbuild.included_at:
            incl_at_offset_str = self._mk_offset(len(build_title), 1)
            incl_at_offset_str += " / "
            build_title += " / "
            build_title += self._mk_included_at_descr(rbuild.included_at[0])
        yield build_title

        # yiled remaining lines of 'included_at' section
        for incl_at in rbuild.included_at[1:]:
            yield incl_at_offset_str + self._mk_included_at_descr(incl_at)

        for comp_name, bump in rbuild.bumps.items():
            yield from self._gen_bump_descr(comp_name, bump, offset + 1)
        for rc in rbuild.get_printable_rcommits():
            yield from self.gen_commit_descr(rc.commit, commits_merged, offset + 1)

    def _mk_buildnum_descr(self, build_num):
        # BuildNumData -> ColoredText
        if build_num.is_fake_not_built():
            return self.palette['VER_NOT_BUILT']("- not built -")
        elif build_num.is_fake_not_merged():
            return self.palette['VER_NOT_MERGED']("- not merged -")

        return self.palette['VERSION'](str(build_num))

    def _mk_included_at_descr(self, incl_at):
        # prepare description of the parent component's build:
        # "parent_repo relese/3.4 10.15.35"
        repo_id = self.palette['REPO'](incl_at[0])
        branch_name = self.palette['BRANCH'](incl_at[1])
        build = self._mk_buildnum_descr(incl_at[2])
        return f"{repo_id} {branch_name} {build}"

    def _gen_bump_descr(self, comp_name, bump, offset):
        # generate lines of bump description for a parent component:
        # Example:
        # "      proj_lib=10.20.9<-10.20.7"
        # "      proj_lib1=3.4.5"
        bump_versions_descr = self.palette['VERSION'](str(bump.to_buildnum))
        if bump.from_build_nums:
            bump_versions_descr += "<-"
            if len(bump.from_build_nums) == 1:
                bump_versions_descr += self.palette['VERSION'](
                    str(bump.from_build_nums[0]))
            else:
                bump_versions_descr += "["
                bump_versions_descr += ColoredText(", ").join(
                    str(bn) for bn in bump.from_build_nums)
                bump_versions_descr += "]"
        yield (
            self._mk_offset(offset + 1) +
            self.palette['REPO'](comp_name) + "=" + bump_versions_descr)

    def gen_commit_descr(self, commit, merged, offset):
        """Generate ColoredText lines of a single commit descripiton."""
        t_hexsha = self.palette['HASH' if merged else 'HASH_NOT_MERGED'](
            commit.hexsha[:11])
        t_time = self.palette['COMMIT_TIME'](
            datetime.fromtimestamp(commit.committed_date).isoformat(sep=' '))
        t_name = self.palette['COMMIT_NAME'](
            commit.author.name).fixed_len(18)
        t_message = commit.message.split('\n')[0].strip()

        yield ColoredText("  " * offset) + ColoredText(" ").join((
            t_hexsha, t_time, t_name, t_message))

    def _mk_offset(self, offset, _step=2):
        return ColoredText(" " * (offset * _step))


def find_commit_chain(from_commit, to_commit, except_commit=None):
    if except_commit is None:
        except_commit = lambda x: False
    visited_commits = set()
    for commit in from_commit.traverse(
        prune=lambda commit, _depth: (
            commit in visited_commits or except_commit(commit)
        )
    ):
        visited_commits.add(commit)
        if commit == to_commit:
            return True
    return False
