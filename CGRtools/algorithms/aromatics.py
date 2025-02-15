# -*- coding: utf-8 -*-
#
#  Copyright 2018-2021 Ramil Nugmanov <nougmanoff@protonmail.com>
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
from CachedMethods import class_cached_property
from collections import defaultdict, deque
from typing import List, Optional, Tuple, TYPE_CHECKING, Union
from .._functions import lazy_product
from ..containers import query  # cyclic imports resolve
from ..exceptions import InvalidAromaticRing
from ..periodictable import ListElement


if TYPE_CHECKING:
    from CGRtools import MoleculeContainer


class Aromatize:
    __slots__ = ()

    def thiele(self: 'MoleculeContainer', *, fix_tautomers=True, fix_metal_organics=True) -> bool:
        """
        Convert structure to aromatic form (Huckel rule ignored). Return True if found any kekule ring.
        Also marks atoms as aromatic.

        :param fix_tautomers: try to fix condensed rings with pyroles.
            N1C=CC2=NC=CC2=C1>>N1C=CC2=CN=CC=C12
        :param fix_metal_organics: create neutral form of ferrocenes and imidazolium complexes.
        """
        atoms = self._atoms
        bonds = self._bonds
        sh = self._hybridizations
        charges = self._charges
        hydrogens = self._hydrogens

        rings = defaultdict(set)  # aromatic? skeleton. include quinones
        tetracycles = []
        pyroles = set()
        acceptors = set()
        donors = []
        freaks = []
        fixed_charges = {}
        for ring in self.sssr:
            lr = len(ring)
            if not 3 < lr < 8:  # skip 3-membered and big rings
                continue
            sp2 = sum(sh[n] == 2 and atoms[n].atomic_number in (5, 6, 7, 8, 15, 16) for n in ring)
            if sp2 == lr:  # benzene like
                if lr == 4:  # two bonds condensed aromatic rings
                    tetracycles.append(ring)
                else:
                    if fix_tautomers and lr % 2:  # find potential pyroles
                        try:
                            n = next(n for n in ring if atoms[n].atomic_number == 7 and not charges[n])
                        except StopIteration:
                            pass
                        else:
                            acceptors.add(n)
                    n, *_, m = ring
                    rings[n].add(m)
                    rings[m].add(n)
                    for n, m in zip(ring, ring[1:]):
                        rings[n].add(m)
                        rings[m].add(n)
            elif 4 < lr == sp2 + 1:  # pyroles, furanes, etc
                try:
                    n = next(n for n in ring if sh[n] == 1)
                except StopIteration:  # exotic, just skip
                    continue
                an = atoms[n].atomic_number
                if lr == 7 and an != 5:  # skip electron-rich 7-membered rings
                    continue
                elif an in (5, 7, 8, 15, 16, 34) and not charges[n]:
                    if fix_tautomers and lr == 6 and an == 7 and len(bonds[n]) == 2:
                        donors.append(n)
                    elif fix_metal_organics and lr == 5 and an == 7:
                        try:  # check for imidazolium. CN1C=C[N+](C)=C1[Cu,Ag,Au-]X
                            m = next(m for m in bonds[n] if atoms[m].atomic_number == 6 and len(bonds[m]) == 3 and
                                     all(atoms[x].atomic_number in (29, 47, 79, 46) and charges[x] < 0 or
                                         atoms[x].atomic_number == 7 and charges[x] == 1
                                         for x in bonds[m] if x != n))
                        except StopIteration:
                            pass
                        else:
                            for x in bonds[m]:
                                if charges[x] < 0:
                                    if x in fixed_charges:
                                        fixed_charges[x] += 1
                                    else:
                                        fixed_charges[x] = charges[x] + 1
                                else:
                                    fixed_charges[x] = 0
                    pyroles.add(n)
                    n, *_, m = ring
                    rings[n].add(m)
                    rings[m].add(n)
                    for n, m in zip(ring, ring[1:]):
                        rings[n].add(m)
                        rings[m].add(n)
                elif an == 6 and lr == 5 and charges[n] == -1:  # ferrocene, etc.
                    if fix_metal_organics:
                        try:
                            m = next(m for m, b in bonds[n].items() if b == 8 and charges[m] > 0 and
                                     atoms[m].atomic_number in
                                     (22, 23, 24, 25, 26, 27, 28, 40, 41, 42, 44, 72, 74, 75, 77))
                        except StopIteration:
                            pass
                        else:
                            fixed_charges[n] = 0  # remove charges in thiele form
                            if m in fixed_charges:
                                fixed_charges[m] -= 1
                            else:
                                fixed_charges[m] = charges[m] - 1
                    pyroles.add(n)
                    n, *_, m = ring
                    rings[n].add(m)
                    rings[m].add(n)
                    for n, m in zip(ring, ring[1:]):
                        rings[n].add(m)
                        rings[m].add(n)
            # like N1C=Cn2cccc12
            elif lr == 5 and sum(atoms[x].atomic_number == 7 and not charges[x] for x in ring) > 1:
                freaks.append(ring)
        if not rings:
            return False
        double_bonded = {n for n in rings if any(m not in rings and b.order == 2 for m, b in bonds[n].items())}

        # fix_tautomers
        if fix_tautomers and acceptors and donors:
            for start in donors:
                stack = [(start, n, 0, 2) for n in rings[start] if n not in double_bonded]
                path = []
                seen = {start}
                while stack:
                    last, current, depth, order = stack.pop()
                    if len(path) > depth:
                        seen.difference_update(x for _, x, _ in path[depth:])
                        path = path[:depth]
                    path.append((last, current, order))
                    if current in acceptors:  # we found
                        if order == 1:
                            acceptors.discard(current)
                            pyroles.discard(start)
                            pyroles.add(current)
                            hydrogens[current] = 1
                            hydrogens[start] = 0
                            break
                        else:
                            continue

                    depth += 1
                    seen.add(current)
                    new_order = 1 if order == 2 else 2
                    stack.extend((current, n, depth, new_order) for n in rings[current] if
                                 n not in seen and n not in double_bonded and bonds[current][n].order == order)
                for n, m, o in path:
                    bonds[n][m]._Bond__order = o
                if not acceptors:
                    break

        if double_bonded:  # delete quinones
            for n in double_bonded:
                for m in rings.pop(n):
                    rings[m].discard(n)

            for n in [n for n, ms in rings.items() if not ms]:  # imide leads to isolated atoms
                del rings[n]
            if not rings:
                return False
            while True:
                try:
                    n = next(n for n, ms in rings.items() if len(ms) == 1)
                except StopIteration:
                    break
                m = rings.pop(n).pop()
                if n in pyroles:
                    rings[m].discard(n)
                else:
                    pm = rings.pop(m)
                    pm.discard(n)
                    for x in pm:
                        rings[x].discard(m)
        if not rings:
            return False

        n_sssr = sum(len(x) for x in rings.values()) // 2 - len(rings) + len(self._connected_components(rings))
        if not n_sssr:
            return False
        rings = self._sssr(rings, n_sssr)  # search rings again

        seen = set()
        for ring in rings:
            seen.update(ring)
        for n in seen:
            sh[n] = 4
        charges.update(fixed_charges)

        # reset bonds to single
        for ring in tetracycles:
            if seen.issuperset(ring):
                n, *_, m = ring
                bonds[n][m]._Bond__order = 1
                for n, m in zip(ring, ring[1:]):
                    bonds[n][m]._Bond__order = 1

        for ring in rings:
            n, *_, m = ring
            bonds[n][m]._Bond__order = 4
            for n, m in zip(ring, ring[1:]):
                bonds[n][m]._Bond__order = 4

        self.flush_cache()
        for ring in freaks:  # aromatize rule based
            rs = set(ring)
            for q in self.__freaks:
                # used low-level API for speedup
                components, closures = q._compiled_query
                if any(q._get_mapping(components[0], closures, atoms, bonds, rs, self.atoms_order)):
                    n, *_, m = ring
                    bonds[n][m]._Bond__order = 4
                    for n, m in zip(ring, ring[1:]):
                        bonds[n][m]._Bond__order = 4
                    for n in ring:
                        sh[n] = 4
                    break
        if freaks:
            self.flush_cache()  # flush again
        self._fix_stereo()  # check if any stereo centers vanished.
        return True

    def kekule(self: Union['Aromatize', 'MoleculeContainer']) -> bool:
        """
        Convert structure to kekule form. Return True if found any aromatic ring. Set implicit hydrogen count and
        hybridization marks on atoms.

        Only one of possible double/single bonds positions will be set.
        For enumerate bonds positions use `enumerate_kekule`.
        """
        kekule = next(self.__kekule_full(), None)
        if kekule:
            self.__kekule_patch(kekule)
            self.flush_cache()
            return True
        return False

    def enumerate_kekule(self: Union['Aromatize', 'MoleculeContainer']):
        """
        Enumerate all possible kekule forms of molecule.
        """
        for form in self.__kekule_full():
            copy = self.copy()
            copy._Aromatize__kekule_patch(form)
            yield copy

    def check_thiele(self, fast=True) -> bool:
        """
        Check basic aromaticity errors of molecule.

        :param fast: don't try to solve kekule form
        """
        try:
            if fast:
                self.__prepare_rings()
            else:
                next(self.__kekule_full(), None)
        except InvalidAromaticRing:
            return False
        return True

    def __fix_rings(self: Union['MoleculeContainer', 'Aromatize']):
        bonds = self._bonds
        seen = set()
        for q, af, bf in self.__bad_rings_rules:
            for mapping in q.get_mapping(self, automorphism_filter=False):
                match = set(mapping.values())
                if not match.isdisjoint(seen):  # prevent double patching of atoms
                    continue
                seen.update(match)

                for n, fix in af.items():
                    n = mapping[n]
                    for key, value in fix.items():
                        getattr(self, key)[n] = value
                for n, m, b in bf:
                    n = mapping[n]
                    m = mapping[m]
                    bonds[n][m]._Bond__order = b
        if seen:
            self.flush_cache()

    def __prepare_rings(self: 'MoleculeContainer'):
        atoms = self._atoms
        charges = self._charges
        radicals = self._radicals
        bonds = self._bonds
        hydrogens = self._hydrogens

        rings = defaultdict(list)  # aromatic skeleton
        pyroles = set()

        double_bonded = defaultdict(list)
        triple_bonded = set()
        for n, m_bond in bonds.items():
            for m, bond in m_bond.items():
                bo = bond.order
                if bo == 4:
                    rings[n].append(m)
                elif bo == 2:
                    double_bonded[n].append(m)
                elif bo == 3:
                    triple_bonded.add(n)

        if not rings:
            return rings, pyroles, set()
        elif not triple_bonded.isdisjoint(rings):
            raise InvalidAromaticRing('triple bonds connected to rings')

        copy_rings = {n: ms.copy() for n, ms in rings.items()}
        for r in self.sssr:
            if set(r).issubset(rings):
                n, *_, m = r
                if n not in rings[m]:  # fix invalid structures: c1ccc-cc1
                    # remove inner ring double bonds: c1ccc=cc1
                    if n in double_bonded and m in double_bonded and m in double_bonded[n]:
                        double_bonded[n].remove(m)
                        double_bonded[m].remove(n)
                    rings[m].append(n)
                    rings[n].append(m)
                elif m in copy_rings[n]:
                    copy_rings[n].remove(m)
                    copy_rings[m].remove(n)
                for n, m in zip(r, r[1:]):
                    if n not in rings[m]:
                        if n in double_bonded and m in double_bonded and m in double_bonded[n]:
                            double_bonded[n].remove(m)
                            double_bonded[m].remove(n)
                        rings[m].append(n)
                        rings[n].append(m)
                    elif m in copy_rings[n]:
                        copy_rings[n].remove(m)
                        copy_rings[m].remove(n)

        if any(len(ms) not in (2, 3) for ms in rings.values()):
            raise InvalidAromaticRing('not in ring aromatic bond or hypercondensed rings: '
                                      f'{{{", ".join(str(n) for n, ms in rings.items() if len(ms) not in (2, 3))}}}')

        # fix invalid smiles: c1ccccc1c2ccccc2 instead of c1ccccc1-c2ccccc2
        seen = set()
        for n, ms in copy_rings.items():
            if ms:
                seen.add(n)
                for m in ms:
                    if m not in seen:
                        rings[n].remove(m)
                        rings[m].remove(n)
                        bonds[n][m]._Bond__order = 1

        # get double bonded ring atoms
        double_bonded = {n for n, ms in double_bonded.items() if ms and n in rings}
        if any(len(rings[n]) != 2 for n in double_bonded):  # double bonded never condensed
            raise InvalidAromaticRing('quinone valence error')
        for n in double_bonded:
            if atoms[n].atomic_number == 7:
                if charges[n] != 1:
                    raise InvalidAromaticRing('quinone should be charged N atom')
            elif atoms[n].atomic_number not in (6, 15, 16, 33, 34, 52) or charges[n]:
                raise InvalidAromaticRing('quinone should be neutral S, Se, Te, C, P, As atom')

        for n in rings:
            an = atoms[n].atomic_number
            ac = charges[n]
            ab = len(bonds[n])
            if an == 6:  # carbon
                if ac == 0:
                    if ab not in (2, 3):
                        raise InvalidAromaticRing
                elif ac in (-1, 1):
                    if radicals[n]:
                        if ab == 2:
                            double_bonded.add(n)
                        else:
                            raise InvalidAromaticRing
                    elif ab == 3:
                        double_bonded.add(n)
                    elif ab == 2:  # benzene an[cat]ion or pyrole
                        pyroles.add(n)
                    else:
                        raise InvalidAromaticRing
                else:
                    raise InvalidAromaticRing
            elif an in (7, 15, 33):
                if ac == 0:  # pyrole or pyridine. include radical pyrole
                    if radicals[n]:
                        if ab != 2:
                            raise InvalidAromaticRing
                        double_bonded.add(n)
                    elif ab == 3:
                        if an == 7:  # pyrole only possible
                            double_bonded.add(n)
                        else:  # P(III) or P(V)H
                            pyroles.add(n)
                    elif ab == 2:
                        ah = hydrogens[n]
                        if ah is None:
                            pyroles.add(n)
                        elif ah == 1:  # only pyrole
                            double_bonded.add(n)
                        elif ah:
                            raise InvalidAromaticRing
                    elif ab != 4 or an not in (15, 33):  # P(V) in ring
                        raise InvalidAromaticRing
                elif ac == -1:  # pyrole only
                    if ab != 2 or radicals[n]:
                        raise InvalidAromaticRing
                    double_bonded.add(n)
                elif ac != 1:
                    raise InvalidAromaticRing
                elif radicals[n]:
                    if ab != 2:  # not cation-radical pyridine
                        raise InvalidAromaticRing
                elif ab == 2:  # pyrole cation or protonated pyridine
                    pyroles.add(n)
                elif ab != 3:  # not pyridine oxyde
                    raise InvalidAromaticRing
            elif an == 8:  # furan
                if ab == 2:
                    if ac == 0:
                        if radicals[n]:
                            raise InvalidAromaticRing('radical oxygen')
                        double_bonded.add(n)
                    elif ac == 1:
                        if radicals[n]:  # furan cation-radical
                            double_bonded.add(n)
                        # pyrylium
                    else:
                        raise InvalidAromaticRing('invalid oxygen charge')
                else:
                    raise InvalidAromaticRing('Triple-bonded oxygen')
            elif an in (16, 34, 52):  # thiophene
                if n not in double_bonded:  # not sulphoxyde or sulphone
                    if ab == 2:
                        if radicals[n]:
                            if ac == 1:
                                double_bonded.add(n)
                            else:
                                raise InvalidAromaticRing('S, Se, Te cation-radical expected')
                        if ac == 0:
                            double_bonded.add(n)
                        elif ac != 1:
                            raise InvalidAromaticRing('S, Se, Te cation in benzene like ring expected')
                    elif ab == 3 and ac == 1 and not radicals[n]:
                        double_bonded.add(n)
                    else:
                        raise InvalidAromaticRing('S, Se, Te hypervalent ring')
            elif an == 5:  # boron
                if ac == 0:
                    if ab == 2:
                        if radicals[n]:  # C=1O[B]OC=1
                            double_bonded.add(n)
                        else:
                            ah = hydrogens[n]
                            if ah is None:  # b1ccccc1, C=1OBOC=1 or B1C=CC=N1
                                pyroles.add(n)
                            elif ah == 1:  # C=1O[BH]OC=1 or [BH]1C=CC=N1
                                double_bonded.add(n)
                            elif ah:
                                raise InvalidAromaticRing
                    elif not radicals[n]:
                        double_bonded.add(n)
                    else:
                        raise InvalidAromaticRing
                elif ac == 1:
                    if ab == 2 and not radicals[n]:
                        double_bonded.add(n)
                    else:
                        raise InvalidAromaticRing
                elif ac == -1:
                    if ab == 2:
                        if not radicals[n]:  # C=1O[B-]OC=1 or [bH-]1ccccc1
                            pyroles.add(n)
                        # anion-radical is benzene like
                    elif radicals[n]:  # C=1O[B-*](R)OC=1
                        double_bonded.add(n)
                    else:
                        pyroles.add(n)
                else:
                    raise InvalidAromaticRing
            else:
                raise InvalidAromaticRing(f'only B, C, N, P, O, S, Se, Te possible, not: {atoms[n].atomic_symbol}')
        return rings, pyroles, double_bonded

    def __kekule_patch(self: 'MoleculeContainer', patch):
        bonds = self._bonds
        atoms = set()
        for n, m, b in patch:
            bonds[n][m]._Bond__order = b
            atoms.add(n)
            atoms.add(m)
        for n in atoms:
            self._calc_hybridization(n)
            self._calc_implicit(n)

    def __kekule_full(self):
        self.__fix_rings()  # fix pyridine n-oxyde
        rings, pyroles, double_bonded = self.__prepare_rings()
        atoms = set(rings)
        components = []
        while atoms:
            start = atoms.pop()
            component = {start: rings[start]}
            queue = deque([start])
            while queue:
                current = queue.popleft()
                for n in rings[current]:
                    if n not in component:
                        queue.append(n)
                        component[n] = rings[n]

            components.append(component)
            atoms.difference_update(component)

        for keks in lazy_product(*(self._kekule_component(c, double_bonded & c.keys(), pyroles & c.keys())
                                   for c in components)):
            yield [x for x in keks for x in x]

    @staticmethod
    def _kekule_component(rings, double_bonded, pyroles):
        # (current atom, previous atom, bond between cp atoms, path deep for cutting [None if cut impossible])
        stack: List[List[Tuple[int, int, int, Optional[int]]]]
        if double_bonded:  # start from double bonded if exists
            start = next(iter(double_bonded))
            stack = [[(next(iter(rings[start])), start, 1, 0)]]
        else:  # select not pyrole not condensed atom
            try:
                start = next(n for n, ms in rings.items() if len(ms) == 2 and n not in pyroles)
            except StopIteration:  # all pyroles. select not condensed atom.
                try:
                    start = next(n for n, ms in rings.items() if len(ms) == 2)
                except StopIteration:  # fullerene?
                    start = next(iter(rings))
                    double_bonded.add(start)
                    stack = [[(next_atom, start, 2, 0)] for next_atom in rings[start]]
                else:
                    stack = [[(next_atom, start, 1, 0)] for next_atom in rings[start]]
            else:
                stack = [[(next_atom, start, 1, 0)] for next_atom in rings[start]]

        size = sum(len(x) for x in rings.values()) // 2
        path = []
        hashed_path = set()
        nether_yielded = True

        while stack:
            atom, prev_atom, bond, _ = stack[-1].pop()
            path.append((atom, prev_atom, bond))
            hashed_path.add(atom)

            if len(path) == size:
                yield path
                if nether_yielded:
                    nether_yielded = False
                del stack[-1]
                if stack:
                    path = path[:stack[-1][-1][-1]]
                    hashed_path = {x for x, *_ in path}
            elif atom != start:
                for_stack = []
                closures = []
                loop = 0
                for next_atom in rings[atom]:
                    if next_atom == prev_atom:  # only forward. behind us is the homeland
                        continue
                    elif next_atom == start:
                        loop = next_atom
                    elif next_atom in hashed_path:  # closure found
                        closures.append(next_atom)
                    else:
                        for_stack.append(next_atom)

                if loop:  # we found starting point.
                    if bond == 2:  # finish should be single bonded
                        if double_bonded:  # ok
                            stack[-1].insert(0, (loop, atom, 1, None))
                        else:
                            del stack[-1]
                            if stack:
                                path = path[:stack[-1][-1][-1]]
                                hashed_path = {x for x, *_ in path}
                            continue
                    elif double_bonded:  # we in quinone ring. finish should be single bonded
                        # side-path for storing double bond or atom is quinone or pyrole
                        if for_stack or atom in double_bonded or atom in pyroles:
                            stack[-1].insert(0, (loop, atom, 1, None))
                        else:
                            del stack[-1]
                            if stack:
                                path = path[:stack[-1][-1][-1]]
                                hashed_path = {x for x, *_ in path}
                            continue
                    else:  # finish should be double bonded
                        stack[-1].insert(0, (loop, atom, 2, None))
                        bond = 2  # grow should be single bonded

                if bond == 2 or atom in double_bonded:  # double in - single out. quinone has two single bonds
                    for next_atom in closures:
                        path.append((next_atom, atom, 1))  # closures always single-bonded
                        stack[-1].remove((atom, next_atom, 1, None))  # remove fork from stack
                    for next_atom in for_stack:
                        stack[-1].append((next_atom, atom, 1, None))
                elif len(for_stack) == 1:  # easy path grow. next bond double or include single for pyroles
                    next_atom = for_stack[0]
                    if next_atom in double_bonded:  # need double bond, but next atom quinone
                        if atom in pyroles:
                            stack[-1].append((next_atom, atom, 1, None))
                        else:
                            del stack[-1]
                            if stack:
                                path = path[:stack[-1][-1][-1]]
                                hashed_path = {x for x, *_ in path}
                    else:
                        if atom in pyroles:  # try pyrole and pyridine
                            opposite = stack[-1].copy()
                            opposite.append((next_atom, atom, 2, None))
                            stack[-1].append((next_atom, atom, 1, len(path)))
                            stack.append(opposite)
                        else:
                            stack[-1].append((next_atom, atom, 2, None))
                            if closures:
                                next_atom = closures[0]
                                path.append((next_atom, atom, 1))  # closures always single-bonded
                                stack[-1].remove((atom, next_atom, 1, None))  # remove fork from stack
                elif for_stack:  # fork
                    next_atom1, next_atom2 = for_stack
                    if next_atom1 in double_bonded:  # quinone next from fork
                        if next_atom2 in double_bonded:  # bad path
                            del stack[-1]
                            if stack:
                                path = path[:stack[-1][-1][-1]]
                                hashed_path = {x for x, *_ in path}
                        else:
                            stack[-1].append((next_atom1, atom, 1, None))
                            stack[-1].append((next_atom2, atom, 2, None))
                    elif next_atom2 in double_bonded:  # quinone next from fork
                        stack[-1].append((next_atom2, atom, 1, None))
                        stack[-1].append((next_atom1, atom, 2, None))
                    else:  # new path
                        opposite = stack[-1].copy()
                        stack[-1].append((next_atom1, atom, 1, None))
                        stack[-1].append((next_atom2, atom, 2, len(path)))
                        opposite.append((next_atom2, atom, 1, None))
                        opposite.append((next_atom1, atom, 2, None))
                        stack.append(opposite)
                elif closures and atom not in pyroles:  # need double bond, but closure should be single bonded
                    del stack[-1]
                    if stack:
                        path = path[:stack[-1][-1][-1]]
                        hashed_path = {x for x, *_ in path}

        if nether_yielded:
            raise InvalidAromaticRing(f'kekule form not found for: {list(rings)}')

    @class_cached_property
    def __freaks(self):
        rules = []

        q = query.QueryContainer()
        q.add_atom('N', neighbors=2)
        q.add_atom('A')
        q.add_atom('A')
        q.add_atom('A')
        q.add_atom('A')
        q.add_bond(1, 2, 1)
        q.add_bond(2, 3, (2, 4))
        q.add_bond(3, 4, 1)
        q.add_bond(4, 5, 4)
        q.add_bond(1, 5, 1)
        rules.append(q)
        return rules

    @class_cached_property
    def __bad_rings_rules(self):
        rules = []

        # Aromatic N-Oxide
        #
        #  : N :  >>  : [N+] :
        #    \\           \
        #     O           [O-]
        #
        q = query.QueryContainer()
        q.add_atom('N', neighbors=3, hybridization=4)
        q.add_atom('O', neighbors=1)
        q.add_bond(1, 2, 2)
        atom_fix = {1: {'_charges': 1}, 2: {'_charges': -1, '_hybridizations': 1}}
        bonds_fix = ((1, 2, 1),)
        rules.append((q, atom_fix, bonds_fix))

        # Aromatic N-Nitride?
        #
        #  : N :  >>  : [N+] :
        #    \\           \
        #     N           [N-]
        #
        q = query.QueryContainer()
        q.add_atom('N', neighbors=3, hybridization=4)
        q.add_atom('N', neighbors=(1, 2), hybridization=2)
        q.add_bond(1, 2, 2)
        atom_fix = {1: {'_charges': 1}, 2: {'_charges': -1, '_hybridizations': 1}}
        bonds_fix = ((1, 2, 1),)
        rules.append((q, atom_fix, bonds_fix))

        #
        # : [S+] : >> : S :
        #    |          \\
        #   [O-]         O
        #
        q = query.QueryContainer()
        q.add_atom('S', neighbors=3, hybridization=4, charge=1)
        q.add_atom('O', neighbors=1, charge=-1)
        q.add_bond(1, 2, 1)
        atom_fix = {1: {'_charges': 0}, 2: {'_charges': 0, '_hybridizations': 2}}
        bonds_fix = ((1, 2, 2),)
        rules.append((q, atom_fix, bonds_fix))

        #
        # [O-]-N:C:C:[N+]=O
        #
        q = query.QueryContainer()
        q.add_atom('O', neighbors=1, charge=-1)
        q.add_atom('N', neighbors=3)
        q.add_atom('C')
        q.add_atom('C')
        q.add_atom('N', neighbors=3, charge=1)
        q.add_atom('O', neighbors=1)
        q.add_bond(1, 2, 1)
        q.add_bond(2, 3, 4)
        q.add_bond(3, 4, 4)
        q.add_bond(4, 5, 4)
        q.add_bond(5, 6, 2)
        atom_fix = {2: {'_charges': 1}, 6: {'_charges': -1}}
        bonds_fix = ((5, 6, 1),)
        rules.append((q, atom_fix, bonds_fix))

        #
        # N : A : N - ?
        #  :     :
        #   C # C
        q = query.QueryContainer()
        q.add_atom('N', neighbors=2)
        q.add_atom('C', neighbors=2)
        q.add_atom('C', neighbors=2)
        q.add_atom('N', neighbors=(2, 3))
        q.add_atom(ListElement(['C', 'N']))
        q.add_bond(1, 2, 4)
        q.add_bond(2, 3, 3)
        q.add_bond(3, 4, 4)
        q.add_bond(4, 5, 4)
        q.add_bond(1, 5, 4)
        atom_fix = {}
        bonds_fix = ((2, 3, 4),)
        rules.append((q, atom_fix, bonds_fix))

        #
        # C:[N+]:[C-]
        #    \\
        #     O
        #
        q = query.QueryContainer()
        q.add_atom('N', neighbors=3, charge=1)
        q.add_atom('O', neighbors=1)
        q.add_atom('C', neighbors=(2, 3), charge=-1)
        q.add_atom('C', neighbors=(2, 3))
        q.add_bond(1, 2, 2)
        q.add_bond(1, 3, 4)
        q.add_bond(1, 4, 4)
        atom_fix = {2: {'_charges': -1, '_hybridizations': 1}, 3: {'_charges': 0}}
        bonds_fix = ((1, 2, 1),)
        rules.append((q, atom_fix, bonds_fix))

        #
        #  O=[N+] : C
        #     :     :
        #    O : N : C
        q = query.QueryContainer()
        q.add_atom('N', neighbors=3, charge=1)
        q.add_atom('O', neighbors=1)
        q.add_atom('O', neighbors=2)
        q.add_atom('C', neighbors=(2, 3))
        q.add_atom('C', neighbors=(2, 3))
        q.add_atom('N', neighbors=(2, 3))
        q.add_bond(1, 2, 2)
        q.add_bond(1, 3, 4)
        q.add_bond(1, 4, 4)
        q.add_bond(3, 6, 4)
        q.add_bond(4, 5, 4)
        q.add_bond(5, 6, 4)
        atom_fix = {1: {'_hybridizations': 2}, 3: {'_hybridizations': 1}, 4: {'_hybridizations': 2},
                    5: {'_hybridizations': 2}, 6: {'_hybridizations': 1}}
        bonds_fix = ((1, 3, 1), (1, 4, 1), (3, 6, 1), (4, 5, 2), (5, 6, 1))
        rules.append((q, atom_fix, bonds_fix))

        # todo: refactor!

        # imidazolium
        #         R - N : C                  R - N : C
        #            :    :                    :     :
        #  A - Pd - C     : >>    A - [Pd-2] - C      :
        #            :    :                    :     :
        #         R - N : C                R - [N+]: C
        #
        q = query.QueryContainer()  # bis Pd complex
        q.add_atom('Pd')
        q.add_atom('C', rings_sizes=5, neighbors=3)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_atom('C', rings_sizes=5, neighbors=3)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_bond(1, 2, 1)
        q.add_bond(2, 3, 4)
        q.add_bond(2, 4, 4)
        q.add_bond(1, 5, 1)
        q.add_bond(5, 6, 4)
        q.add_bond(5, 7, 4)
        atom_fix = {1: {'_charges': -2}, 3: {'_charges': 1}, 6: {'_charges': 1}}
        bonds_fix = ()
        rules.append((q, atom_fix, bonds_fix))

        q = query.QueryContainer()
        q.add_atom(ListElement(['Cu', 'Ag', 'Au', 'Pd']))
        q.add_atom('C', rings_sizes=5, neighbors=3)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_atom('N', rings_sizes=5, neighbors=3, heteroatoms=0)
        q.add_bond(1, 2, 1)
        q.add_bond(2, 3, 4)
        q.add_bond(2, 4, 4)
        atom_fix = {1: {'_charges': -1}, 3: {'_charges': 1}}
        bonds_fix = ()
        rules.append((q, atom_fix, bonds_fix))

        # ferrocene uncharged
        #
        q = query.QueryContainer()
        q.add_atom(ListElement(['Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni',
                                'Zr', 'Nb', 'Mo', 'Ru', 'Hf', 'W', 'Re', 'Ir']))
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_bond(1, 2, 8)
        q.add_bond(1, 7, 8)
        q.add_bond(2, 3, 4)
        q.add_bond(3, 4, 4)
        q.add_bond(4, 5, 4)
        q.add_bond(5, 6, 4)
        q.add_bond(2, 6, 4)
        q.add_bond(7, 8, 4)
        q.add_bond(8, 9, 4)
        q.add_bond(9, 10, 4)
        q.add_bond(10, 11, 4)
        q.add_bond(7, 11, 4)
        atom_fix = {1: {'_charges': 2}, 2: {'_charges': -1}, 7: {'_charges': -1}}
        bonds_fix = ()
        rules.append((q, atom_fix, bonds_fix))

        # half ferrocene uncharged
        #
        q = query.QueryContainer()
        q.add_atom(ListElement(['Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni',
                                'Zr', 'Nb', 'Mo', 'Ru', 'Hf', 'W', 'Re', 'Ir']))
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_atom('C', rings_sizes=5)
        q.add_bond(1, 2, 8)
        q.add_bond(2, 3, 4)
        q.add_bond(3, 4, 4)
        q.add_bond(4, 5, 4)
        q.add_bond(5, 6, 4)
        q.add_bond(2, 6, 4)
        atom_fix = {1: {'_charges': 1}, 2: {'_charges': -1}}
        bonds_fix = ()
        rules.append((q, atom_fix, bonds_fix))
        return rules


__all__ = ['Aromatize']
