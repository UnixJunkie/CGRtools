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
from collections import defaultdict
from itertools import count
from typing import List, TYPE_CHECKING, Union, Tuple, Type
from ...containers import query, molecule  # cyclic imports resolve


if TYPE_CHECKING:
    from CGRtools import ReactionContainer


class StandardizeReaction:
    __slots__ = ()

    def canonicalize(self: 'ReactionContainer', fix_mapping: bool = True, *, logging=False) -> \
            Union[bool, Tuple[int, Tuple[int, ...], int, str]]:
        """
        Convert molecules to canonical forms of functional groups and aromatic rings without explicit hydrogens.
        Works only for Molecules.
        Return True if in any molecule found not canonical group.

        :param fix_mapping: Search AAM errors of functional groups.
        :param logging: return log from molecules with index of molecule at first position.
            Otherwise return True if these groups found in any molecule.
        """
        if logging:
            total = []
        else:
            total = False
        for n, m in enumerate(self.molecules()):
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            out = m.canonicalize(logging=logging)
            if out:
                if logging:
                    total.extend((n, *x) for x in out)
                else:
                    total = True

        if fix_mapping and self.fix_mapping():
            if logging:
                total.append((-1, (), -1, 'mapping fixed'))
                return total
            return True

        if total:
            self.flush_cache()
        return total

    def standardize(self: 'ReactionContainer', fix_mapping: bool = True, *, logging=False) -> \
            Union[bool, Tuple[int, Tuple[int, ...], int, str]]:
        """
        Standardize functional groups. Works only for Molecules.

        :param fix_mapping: Search AAM errors of functional groups.
        :param logging: return log from molecules with index of molecule at first position.
            Otherwise return True if these groups found in any molecule.
        """
        if logging:
            total = []
        else:
            total = False
        for n, m in enumerate(self.molecules()):
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            out = m.standardize(logging=logging)
            if out:
                if logging:
                    total.extend((n, *x) for x in out)
                else:
                    total = True

        if fix_mapping and self.fix_mapping():
            if logging:
                total.append((-1, (), -1, 'mapping fixed'))
                return total
            return True

        if total:
            self.flush_cache()
        return total

    def fix_mapping(self: Union['ReactionContainer', 'StandardizeReaction'], *, logging: bool = False) -> bool:
        """
        Fix atom-to-atom mapping of some functional groups. Return True if found AAM errors.
        """
        if logging:
            log = []
        seen = set()
        if not (self.reactants and self.products):
            return False
        elif not isinstance(self.reactants[0], molecule.MoleculeContainer):
            raise TypeError('Only Molecules supported')

        for r_pattern, p_pattern, fix in self.__standardize_compiled_rules:
            found = []
            for m in self.reactants:
                for mapping in r_pattern.get_mapping(m, automorphism_filter=False):
                    if mapping[1] not in seen:
                        found.append(({fix.get(k, k): v for k, v in mapping.items()},
                                      {mapping[k]: mapping[v] for k, v in fix.items()}))

            if not found:
                continue
            for m in self.products:
                for mapping in p_pattern.get_mapping(m, automorphism_filter=False):
                    atom = mapping[1]
                    if atom in seen:
                        continue
                    for n, (k, v) in enumerate(found):
                        if k == mapping:
                            break
                    else:
                        continue

                    del found[n]
                    m.remap(v)
                    seen.add(atom)
        if seen:
            self.flush_cache()
            flag = True
            seen = set()
        else:
            flag = False

        for rule_num, (bad_query, good_query, fix, valid) in enumerate(self.__remapping_compiled_rules):
            cgr = ~self
            first_free = max(cgr) + 1
            free_number = count(first_free)
            cgr_c = set(cgr.center_atoms)
            del self.__dict__['__cached_method_compose']

            flag_m = False
            for mapping in bad_query.get_mapping(cgr, automorphism_filter=False):
                if not seen.isdisjoint(mapping.values()):  # prevent matching same RC
                    continue
                mapping = {mapping[n]: next(free_number) if m is None else mapping[m] for n, m in fix.items()}
                flag_m = True
                reverse = {m: n for n, m in mapping.items()}
                for m in self.products:
                    m.remap(mapping)

                check = ~self
                check_c = set(check.center_atoms)
                delta = check_c - cgr_c

                for m in good_query.get_mapping(check, automorphism_filter=False):
                    if valid.issubset(m) and delta.issubset(m.values()):
                        seen.update(mapping)
                        if logging:
                            log.append((rule_num, str(bad_query), str(good_query), tuple(mapping.values())))
                        flag = True
                        break
                else:
                    # restore old mapping
                    for m in self.products:
                        m.remap(reverse)
                    del self.__dict__['__cached_method_compose']
                    free_number = count(first_free)
                    continue
                break
            else:
                if logging and flag_m:
                    log.append((rule_num, str(bad_query), str(good_query), ()))
        if seen:
            self.flush_cache()
        if logging:
            return log
        return flag

    @classmethod
    def load_remapping_rules(cls: Type['ReactionContainer'], reactions):
        """
        Load AAM fixing rules. Required pairs of bad mapped and good mapped reactions.
        Reactants in pairs should be fully equal (equal molecules and equal atom orders).
        Products should be equal but with different atom numbers.
        """
        rules = []
        for bad, good in reactions:
            if str(bad) != str(good):
                raise ValueError('bad and good reaction should be equal')

            cgr_good, cgr_bad = ~good, ~bad
            gc = cgr_good.augmented_substructure(cgr_good.center_atoms, deep=1)
            bc = cgr_bad.augmented_substructure(cgr_bad.center_atoms, deep=1)

            atoms = set(bc.atoms_numbers + gc.atoms_numbers)

            pr_g, pr_b, re_g, re_b = set(), set(), set(), set()
            for pr in good.products:
                pr_g.update(pr)
            for pr in bad.products:
                pr_b.update(pr)
            for pr in good.reactants:
                re_g.update(pr)
            for pr in bad.reactants:
                re_b.update(pr)
            atoms.update((re_b.difference(pr_b)).intersection(pr_g))

            strange_atoms = pr_b.difference(pr_g)
            atoms.update(strange_atoms)

            bad_query = cgr_bad.substructure(atoms.intersection(cgr_bad), as_query=True)
            good_query = cgr_good.substructure(atoms.intersection(cgr_good), as_query=True)

            fix = {}
            for mb, mg in zip(bad.products, good.products):
                fix.update({k: v for k, v in zip(mb, mg) if k != v and k in atoms})

            valid = set(fix).difference(strange_atoms)
            rules.append((bad_query, good_query, fix, valid))

        cls.__class_cache__[cls] = {'_StandardizeReaction__remapping_compiled_rules': tuple(rules)}

    @class_cached_property
    def __remapping_compiled_rules(self):
        return ()

    def implicify_hydrogens(self: 'ReactionContainer') -> int:
        """
        Remove explicit hydrogens if possible

        :return: number of removed hydrogens
        """
        total = 0
        for m in self.molecules():
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            total += m.implicify_hydrogens()
        if total:
            self.flush_cache()
        return total

    def explicify_hydrogens(self: 'ReactionContainer') -> int:
        """
        Add explicit hydrogens to atoms

        :return: number of added atoms
        """
        total = 0
        start_map = 0
        for m in self.molecules():
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            map_ = max(m, default=0)
            if map_ > start_map:
                start_map = map_

        mapping = defaultdict(list)
        for m in self.reactants:
            maps = m.explicify_hydrogens(return_maps=True, start_map=start_map + 1)
            if maps:
                for n, h in maps:
                    mapping[n].append(h)
                start_map = maps[-1][1]
                total += len(maps)

        for m in self.reagents:
            maps = m.explicify_hydrogens(return_maps=True, start_map=start_map + 1)
            if maps:
                start_map = maps[-1][1]
                total += len(maps)

        for m in self.products:
            maps = m.explicify_hydrogens(return_maps=True, start_map=start_map + 1)
            if maps:
                total += len(maps)
                remap = {}
                free = []
                for n, h in maps:
                    if n in mapping and mapping[n]:
                        remap[h] = mapping[n].pop()
                        free.append(h)
                    elif free:
                        remap[h] = start_map = free.pop(0)
                    else:
                        start_map = h
                m.remap(remap)

        if total:
            self.flush_cache()
        return total

    def thiele(self: 'ReactionContainer') -> bool:
        """
        Convert structures to aromatic form. Works only for Molecules.
        Return True if in any molecule found kekule ring
        """
        total = False
        for m in self.molecules():
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            if m.thiele() and not total:
                total = True
        if total:
            self.flush_cache()
        return total

    def kekule(self: 'ReactionContainer') -> bool:
        """
        Convert structures to kekule form. Works only for Molecules.
        Return True if in any molecule found aromatic ring
        """
        total = False
        for m in self.molecules():
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            if m.kekule() and not total:
                total = True
        if total:
            self.flush_cache()
        return total

    def clean_isotopes(self: 'ReactionContainer') -> bool:
        """
        Clean isotope marks for all molecules in reaction.
        Returns True if in any molecule found isotope.
        """
        flag = False
        for m in self.molecules():
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            if m.clean_isotopes() and not flag:
                flag = True

        if flag:
            self.flush_cache()
        return flag

    def clean_stereo(self: 'ReactionContainer'):
        """
        Remove stereo data
        """
        for m in self.molecules():
            if not hasattr(m, 'clean_stereo'):
                raise TypeError('Only Molecules and Queries supported')
            m.clean_stereo()
        self.flush_cache()

    def clean2d(self: 'ReactionContainer'):
        """
        Recalculate 2d coordinates
        """
        for m in self.molecules():
            m.clean2d()
        self.fix_positions()

    def fix_positions(self: Union['ReactionContainer', 'StandardizeReaction']):
        """
        Fix coordinates of molecules in reaction
        """
        shift_x = 0
        reactants = self.reactants
        amount = len(reactants) - 1
        signs = []
        for m in reactants:
            max_x = m._fix_plane_mean(shift_x)
            if amount:
                max_x += .2
                signs.append(max_x)
                amount -= 1
            shift_x = max_x + 1
        arrow_min = shift_x

        if self.reagents:
            shift_x += .4
            for m in self.reagents:
                max_x = m._fix_plane_min(shift_x, .5)
                shift_x = max_x + 1
            shift_x += .4
            if shift_x - arrow_min < 3:
                shift_x = arrow_min + 3
        else:
            shift_x += 3
        arrow_max = shift_x - 1

        products = self.products
        amount = len(products) - 1
        for m in products:
            max_x = m._fix_plane_mean(shift_x)
            if amount:
                max_x += .2
                signs.append(max_x)
                amount -= 1
            shift_x = max_x + 1
        self._arrow = (arrow_min, arrow_max)
        self._signs = tuple(signs)
        self.flush_cache()

    def check_valence(self: 'ReactionContainer') -> List[Tuple[int, Tuple[int, ...]]]:
        """
        Check valences of all atoms of all molecules.

        Works only on molecules with aromatic rings in Kekule form.
        :return: list of invalid molecules with invalid atoms lists
        """
        out = []
        for n, m in enumerate(self.molecules()):
            if not isinstance(m, molecule.MoleculeContainer):
                raise TypeError('Only Molecules supported')
            c = m.check_valence()
            if c:
                out.append((n, tuple(c)))
        return out

    @class_cached_property
    def __standardize_compiled_rules(self):
        rules = []
        for (r_atoms, r_bonds), (p_atoms, p_bonds), fix in self.__standardize_rules():
            r_q = query.QueryContainer()
            p_q = query.QueryContainer()
            for a in r_atoms:
                r_q.add_atom(**a)
            for n, m, b in r_bonds:
                r_q.add_bond(n, m, b)
            for a in p_atoms:
                p_q.add_atom(**a)
            for n, m, b in p_bonds:
                p_q.add_bond(n, m, b)
            rules.append((r_q, p_q, fix))
        return rules

    @staticmethod
    def __standardize_rules():
        rules = []

        # Nitro
        #
        #      O
        #     //
        # * - N+
        #      \
        #       O-
        #
        atoms = ({'atom': 'N', 'neighbors': 3, 'hybridization': 2, 'charge': 1},
                 {'atom': 'O', 'neighbors': 1, 'charge': -1}, {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (atoms, bonds), fix))

        # Carbonate
        #
        #      O
        #     //
        # * - C
        #      \
        #       O-
        #
        atoms = ({'atom': 'C', 'neighbors': 3, 'hybridization': 2}, {'atom': 'O', 'neighbors': 1, 'charge': -1},
                 {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (atoms, bonds), fix))

        # Carbon Acid
        #
        #      O
        #     //
        # * - C
        #      \
        #       OH
        #
        atoms = ({'atom': 'C', 'neighbors': 3, 'hybridization': 2}, {'atom': 'O', 'neighbors': 1},
                 {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (atoms, bonds), fix))

        # Phosphate
        #
        #      *
        #      |
        #  * - P = O
        #      |
        #      OH
        #
        atoms = ({'atom': 'P', 'neighbors': 4, 'hybridization': 2}, {'atom': 'O', 'neighbors': 1},
                 {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (atoms, bonds), fix))

        # Nitro addition
        #
        #      O             O -- *
        #     //            /
        # * - N+   >>  * = N+
        #      \            \
        #       O-           O-
        #
        atoms = ({'atom': 'N', 'neighbors': 3, 'charge': 1, 'hybridization': 2},
                 {'atom': 'O', 'neighbors': 1, 'charge': -1}, {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        p_atoms = ({'atom': 'N', 'neighbors': 3, 'charge': 1, 'hybridization': 2},
                   {'atom': 'O', 'neighbors': 1, 'charge': -1}, {'atom': 'O', 'neighbors': 2})
        p_bonds = ((1, 2, 1), (1, 3, 1))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (p_atoms, p_bonds), fix))

        # Sulphate addition
        #
        #      O [3]            O -- * [2]
        #     //               /
        # * = S - *   >>  * = S - *
        #     |               \\
        #     O- [2]           O [3]
        #
        atoms = ({'atom': 'S', 'neighbors': 4, 'hybridization': 3}, {'atom': 'O', 'neighbors': 1, 'charge': -1},
                 {'atom': 'O', 'neighbors': 1})
        bonds = ((1, 2, 1), (1, 3, 2))
        p_atoms = ({'atom': 'S', 'neighbors': 4, 'hybridization': 3}, {'atom': 'O', 'neighbors': 2},
                   {'atom': 'O', 'neighbors': 1})
        p_bonds = ((1, 2, 1), (1, 3, 2))
        fix = {2: 3, 3: 2}
        rules.append(((atoms, bonds), (p_atoms, p_bonds), fix))

        return rules


__all__ = ['StandardizeReaction']
