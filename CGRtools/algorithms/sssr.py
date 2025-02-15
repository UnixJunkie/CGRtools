# -*- coding: utf-8 -*-
#
#  Copyright 2017-2021 Ramil Nugmanov <nougmanoff@protonmail.com>
#  This file is part of CGRtools.
#
#  CGRtools is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, see <https://www.gnu.org/licenses/>.
#
from CachedMethods import cached_property
from collections import defaultdict
from itertools import combinations
from operator import itemgetter
from typing import Any, Dict, Set, Tuple, Union, TYPE_CHECKING, Type, List, Optional
from ..exceptions import ImplementationError


if TYPE_CHECKING:
    from CGRtools.containers.common import Graph


class SSSR:
    """ SSSR calculation. based on idea of PID matrices from:
        Lee, C. J., Kang, Y.-M., Cho, K.-H., & No, K. T. (2009).
        A robust method for searching the smallest set of smallest rings with a path-included distance matrix.
        Proceedings of the National Academy of Sciences of the United States of America, 106(41), 17355–17358.
        http://doi.org/10.1073/pnas.0813040106
    """
    __slots__ = ()

    @cached_property
    def sssr(self: 'Graph') -> Tuple[Tuple[int, ...], ...]:
        """
        Smallest Set of Smallest Rings. Special bonds ignored.

        :return rings atoms numbers
        """
        if self.rings_count:
            return self._sssr(self.not_special_connectivity.copy(), self.rings_count)
        return ()

    @classmethod
    def _sssr(cls: Type[Union['Graph', 'SSSR']], bonds: Dict[int, Union[Set[int], Dict[int, Any]]], n_sssr: int) -> \
            Tuple[Tuple[int, ...], ...]:
        """
        Smallest Set of Smallest Rings of any adjacency matrix.
        Number of rings required.
        """
        bonds = cls._skin_graph(bonds)
        paths = cls.__bfs(bonds)
        pid1, pid2, dist = cls.__make_pid(paths)
        return cls.__rings_filter(cls.__c_set(pid1, pid2, dist), n_sssr)

    @staticmethod
    def __bfs(bonds):
        atoms = set(bonds)
        terminated = []
        tail = atoms.pop()
        next_stack = {x: [tail, x] for x in bonds[tail]}

        while True:
            next_front = set()
            found_odd = set()
            stack, next_stack = next_stack, {}
            for tail, path in stack.items():
                neighbors = bonds[tail] & atoms
                next_front.add(tail)

                if len(neighbors) == 1:
                    n = neighbors.pop()
                    if n in found_odd:
                        if len(path) != 1:
                            terminated.append(tuple(path))  # save second ring closure
                        next_stack[n] = [n]  # maybe we have another path?
                    else:
                        path.append(n)
                        if n in stack:  # odd rings
                            found_odd.add(tail)
                            terminated.append(tuple(path))  # found ring closure. save path.
                        elif n in next_stack:  # even rings
                            terminated.append(tuple(path))
                            if len(next_stack[n]) != 1:  # prevent bicycle case
                                terminated.append(tuple(next_stack[n]))
                                next_stack[n] = [n]
                        else:
                            next_stack[n] = path  # grow must go on
                elif neighbors:
                    if len(path) != 1:
                        terminated.append(tuple(path))  # save path.
                    for n in neighbors:
                        if n in found_odd:
                            if n in stack:
                                if n in next_stack:
                                    del next_stack[n]
                            else:
                                next_stack[n] = [n]
                        else:
                            path = [tail, n]
                            if n in stack:  # odd rings
                                found_odd.add(tail)
                                terminated.append(tuple(path))
                            elif n in next_stack:  # even rings
                                terminated.append(tuple(path))
                                if len(next_stack[n]) != 1:  # prevent bicycle case
                                    terminated.append(tuple(next_stack[n]))
                                    next_stack[n] = [n]
                            else:
                                next_stack[n] = path

            atoms.difference_update(next_front)
            if not atoms:
                break
            elif not next_stack:
                tail = atoms.pop()
                next_stack = {x: [tail, x] for x in bonds[tail] & atoms}
        return terminated

    @staticmethod
    def __make_pid(paths: List[List[int]]):
        pid1 = defaultdict(lambda: defaultdict(dict))
        pid2 = defaultdict(lambda: defaultdict(dict))
        distances = defaultdict(lambda: defaultdict(lambda: 1e9))
        chains = sorted(paths, key=len)
        for c in chains:
            di = len(c) - 1
            n, m = c[0], c[-1]
            nn, mm = c[1], c[-2]
            if n in distances and m in distances[n] and distances[n][m] != di:
                pid2[n][m][(nn, mm)] = c
                pid2[m][n][(mm, nn)] = c[::-1]
            else:
                pid1[n][m][(nn, mm)] = c
                pid1[m][n][(mm, nn)] = c[::-1]
                distances[n][m] = distances[m][n] = di

        for k in pid1:
            new_distances = defaultdict(dict)
            dk = distances[k]
            ndk = new_distances[k]
            for i in pid1:
                if i == k:
                    continue
                di = distances[i]
                ndi = new_distances[i]
                ndk[i] = ndi[k] = di[k]
                for j in pid1:
                    if j == k or j == i:
                        continue
                    ij = di[j]
                    ikj = di[k] + dk[j]
                    if ij - ikj == 1:  # A new shortest path == previous shortest path - 1
                        pid2[i][j] = pid1[i][j]
                        pid1[i][j] = {(ni, mj): ip[:-1] + jp for ((ni, _), ip), ((_, mj), jp) in
                                      zip(pid1[i][k].items(), pid1[k][j].items())}
                        ndi[j] = ikj
                    elif ij > ikj:  # A new shortest path
                        pid2[i][j] = {}
                        pid1[i][j] = {(ni, mj): ip[:-1] + jp for ((ni, _), ip), ((_, mj), jp) in
                                      zip(pid1[i][k].items(), pid1[k][j].items())}
                        ndi[j] = ikj
                    elif ij == ikj:  # Another shortest path
                        pid1[i][j].update({(ni, mj): ip[:-1] + jp for ((ni, _), ip), ((_, mj), jp) in
                                           zip(pid1[i][k].items(), pid1[k][j].items())})
                        ndi[j] = ij
                    elif ikj - ij == 1:  # Shortest+1 path
                        pid2[i][j].update({(ni, mj): ip[:-1] + jp for ((ni, _), ip), ((_, mj), jp) in
                                           zip(pid1[i][k].items(), pid1[k][j].items())})
                        ndi[j] = ij
                    else:
                        ndi[j] = ij
            distances = new_distances
        return pid1, pid2, distances

    @classmethod
    def __c_set(cls, pid1, pid2, pid1l):
        c_set = []
        seen = set()
        for i, p1i in pid1.items():
            seen.add(i)
            di = pid1l[i]
            p2i = pid2[i]

            for j, p1ij in p1i.items():
                if j in seen:
                    continue
                p1ij = list(p1ij.values())
                p2ij = list(p2i[j].values())
                dij = di[j] * 2

                if len(p1ij) == 1:  # one shortest
                    if not p2ij:  # need shortest + 1 path
                        continue
                    c_set.append((dij + 1, p1ij, p2ij))
                elif not p2ij:  # one or more odd rings
                    c_set.append((dij, p1ij, None))
                else:  # odd and even rings found (e.g. bicycle)
                    c_set.append((dij, p1ij, None))
                    c_set.append((dij + 1, p1ij, p2ij))

        for c_num, p1ij, p2ij in sorted(c_set, key=itemgetter(0)):
            if c_num % 2:  # odd rings
                for c1 in p1ij:
                    for c2 in p2ij:
                        c = c1 + c2[-2:0:-1]
                        if len(c) == len(set(c)):
                            yield cls.__canonic_ring(c)
            else:
                for c1, c2 in zip(p1ij, p1ij[1:]):
                    c = c1 + c2[-2:0:-1]
                    if len(c) == len(set(c)):
                        yield cls.__canonic_ring(c)

    @staticmethod
    def __canonic_ring(ring: Tuple[int, ...]) -> Tuple[int, ...]:
        n = min(ring)
        ndx = ring.index(n)
        if ndx == 0:
            if ring[-1] < ring[1]:
                return (n, *ring[:0:-1])
            return ring
        elif ndx == len(ring) - 1:
            if ring[0] > ring[-2]:
                return ring[::-1]
            return (n, *ring[:-1])
        if ring[ndx + 1] > ring[ndx - 1]:
            return (*ring[ndx::-1], *ring[:ndx:-1])
        return (*ring[ndx:], *ring[:ndx])

    @staticmethod
    def __ring_scissors(ring: Tuple[int, ...], n: int, m: int) -> Tuple[int, ...]:
        ndx = ring.index(n)
        mdx = ring.index(m)
        if ndx == 0:
            if mdx == 1:
                return (n, *ring[:0:-1])
            return ring
        elif ndx == len(ring) - 1:
            if mdx == 0:
                return ring[::-1]
            return (n, *ring[:-1])
        if ndx < mdx:
            return (*ring[ndx::-1], *ring[:ndx:-1])
        return (*ring[ndx:], *ring[:ndx])

    @staticmethod
    def __ring_adjacency(ring: Tuple[int, ...]) -> Dict[int, List[int]]:
        adj = {ring[0]: [ring[-1]]}  # ring adjacency matrix
        for n, m in zip(ring, ring[1:]):
            adj[n].append(m)
            adj[m] = [n]
        adj[m].append(ring[0])
        return adj

    @classmethod
    def __is_condensed_ring(cls, c, sssr, seen_rings):
        # create graph of connected neighbour rings
        ck = seen_rings[c]
        neighbors = {x: set() for x in sssr if len(seen_rings[x].keys() & ck.keys()) > 1}
        if len(neighbors) > 1:
            for (i, iv), (j, jv) in combinations(neighbors.items(), 2):
                if len(seen_rings[i].keys() & seen_rings[j].keys()) > 1:
                    iv.add(j)
                    jv.add(i)
            # check if hold rings is combination of existing. (123654) is combo of (1254) and (2365)
            #
            # 1--2--3
            # |  |  |
            # 4--5--6
            #
            # modified NX.dfs_labeled_edges
            # https://networkx.github.io/documentation/stable/reference/algorithms/generated/networkx.algorithms.\
            # traversal.depth_first_search.dfs_labeled_edges.html
            depth_limit = len(neighbors) - 1
            for start, nbrs in neighbors.items():
                if not nbrs:
                    continue
                stack = [(start, seen_rings[start], depth_limit, iter(nbrs), {start})]
                while stack:
                    parent, p_adj, depth_now, children, seen = stack[-1]
                    try:
                        child = next(children)
                    except StopIteration:
                        stack.pop()
                    else:
                        if child not in seen:
                            common = p_adj.keys() & seen_rings[child].keys()
                            if len(common) > 2:  # only terminal common atoms required
                                term = {n for n in common if len(common.intersection(p_adj[n])) == 1}
                                if len(term) != 2:  # skip multiple contacts
                                    continue
                                common.difference_update(term)
                                n, m = term
                                mc = cls.__canonic_ring(
                                        (*cls.__ring_scissors(tuple(x for x in parent if x not in common), n, m),
                                         *cls.__ring_scissors(tuple(x for x in child if x not in common), m, n)[1:-1]))
                            elif len(common) == 2:
                                n, m = common
                                mc = cls.__canonic_ring(
                                        (*cls.__ring_scissors(parent, n, m),
                                         *cls.__ring_scissors(child, m, n)[1:-1]))
                            else:  # point connections
                                continue
                            if c == mc:  # macrocycle found
                                return True
                            elif depth_now and 2 < len(mc) <= len(c) + 1:
                                stack.append((mc, cls.__ring_adjacency(mc), depth_now - 1, iter(neighbors[child]),
                                              {child} | seen))
        return False

    @staticmethod
    def __get_unique_chord(ring: Tuple[int, ...], common: Set[int]) -> Optional[Tuple[int, ...]]:
        lc = len(common)
        if len(ring) == lc:
            if common == set(ring):
                return ()
        else:
            if common == set(ring[:lc]):
                return (*ring[lc - 1:], ring[0])
            for _ in range(len(ring) - 1):
                ring = (*ring[1:], ring[0])
                if common == set(ring[:lc]):
                    return (*ring[lc - 1:], ring[0])

    @classmethod
    def __connected_rings(cls, rings, seen_rings):
        rings = rings.copy()
        out = []
        for i in range(len(rings)):
            c = rings[i]
            ck = seen_rings[c]
            for j in range(i + 1, len(rings)):
                r = rings[j]
                rk = seen_rings[r]
                common = rk.keys() & ck.keys()
                if len(common) == 2:  # one common bond
                    n, m = common
                    if m in ck[n] and m in rk[n]:  # only common bond!
                        c = cls.__canonic_ring((*cls.__ring_scissors(c, n, m), *cls.__ring_scissors(r, m, n)[1:-1]))
                        ck = cls.__ring_adjacency(c)
                        rings[j] = c
                        seen_rings[c] = ck
                        break
                elif len(common) > 2:
                    cc = cls.__get_unique_chord(c, common)
                    if cc is None:  # skip multitouched rings
                        continue
                    r = cls.__get_unique_chord(r, common)
                    if r is None:
                        continue
                    if cc:
                        if r:
                            if r[0] == cc[0]:
                                r = r[::-1]
                            c = cls.__canonic_ring((*cc, *r[1:-1]))
                            ck = cls.__ring_adjacency(c)
                            rings[j] = c
                            seen_rings[c] = ck
                            break
                        else:
                            c = cls.__canonic_ring(cc)
                            ck = cls.__ring_adjacency(c)
                            rings[j] = c
                            seen_rings[c] = ck
                            break
                    elif r:
                        c = cls.__canonic_ring(r)
                        ck = cls.__ring_adjacency(c)
                        rings[j] = c
                        seen_rings[c] = ck
                        break
            else:  # isolated ring[s] found
                out.append(c)
        return out

    @classmethod
    def __rings_filter(cls, rings, n_sssr):
        c = next(rings)
        if n_sssr == 1:
            return c,

        seen_rings = {c}
        sssr_atoms = set(c)
        sssr = [c]
        hold = []
        for c in rings:
            if c in seen_rings:
                continue
            seen_rings.add(c)
            if sssr_atoms.issuperset(c):  # potentially condensed ring
                hold.append(c)
                continue
            sssr_atoms.update(c)
            sssr.append(c)
            if len(sssr) == n_sssr:
                return tuple(sssr)

        # now we have set of plug rings (cuban fullerene), besiege rings and condensed trash
        seen_rings = {c: cls.__ring_adjacency(c) for c in seen_rings}  # prepare adjacency
        condensed_rings = cls.__connected_rings(sssr, seen_rings)  # collection of contours of condensed rings

        for c in hold:
            if c in condensed_rings or cls.__is_condensed_ring(c, sssr, seen_rings):
                continue
            condensed_rings.insert(0, c)
            condensed_rings = cls.__connected_rings(condensed_rings, seen_rings)
            sssr.append(c)
            if len(sssr) == n_sssr:
                return tuple(sorted(sssr, key=len))

        raise ImplementationError('SSSR count not reached')


__all__ = ['SSSR']
