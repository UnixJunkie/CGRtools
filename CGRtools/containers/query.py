# -*- coding: utf-8 -*-
#
#  Copyright 2018, 2019 Ramil Nugmanov <stsouko@live.ru>
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
from typing import List, Tuple, Union
from . import cgr  # cyclic imports resolve
from . import molecule  # cyclic imports resolve
from .common import Graph
from ..periodictable import Element, QueryElement


class QueryContainer(Graph):
    __slots__ = ('_neighbors', '_hybridization', '_atoms_stereo', '_bonds_stereo')

    def __init__(self):
        self._neighbors = {}
        self._hybridization = {}
        self._atoms_stereo = {}
        self._bonds_stereo = {}
        super().__init__()

    def add_atom(self, atom: Union[QueryElement, Element, int, str], _map=None, *, charge=0, is_radical=False, xy=None,
                 neighbors: Union[int, List[int], Tuple[int]] = 0,
                 hybridization: Union[int, List[int], Tuple[int]] = 1):
        if isinstance(neighbors, int):
            if neighbors < 0 or neighbors > 14:
                raise ValueError('neighbors should be in range [0, 14]')
            neighbors = (neighbors,)
        elif isinstance(neighbors, (tuple, list)):
            if any(n < 0 or n > 14 for n in neighbors):
                raise ValueError('neighbors should be in range [0, 14]')
            if len(set(neighbors)) != len(neighbors):
                raise ValueError('neighbors should be unique')
            neighbors = tuple(neighbors)
        else:
            raise TypeError('neighbors should be int or list or tuple of ints')

        if isinstance(hybridization, int):
            if hybridization < 1 or hybridization > 4:
                raise ValueError('hybridization should be in range [1, 4]')
            hybridization = (hybridization,)
        elif isinstance(hybridization, (tuple, list)):
            if any(h < 1 or h > 4 for h in hybridization):
                raise ValueError('neighbors should be in range [0, 14]')
            if len(set(hybridization)) != len(hybridization):
                raise ValueError('hybridizations should be unique')
            hybridization = tuple(hybridization)
        else:
            raise TypeError('hybridization should be int or list or tuple of ints')

        if not isinstance(atom, QueryElement):
            if isinstance(atom, Element):
                atom = QueryElement.from_atomic_number(atom.atomic_number)(atom.isotope)
            elif isinstance(atom, str):
                atom = QueryElement.from_symbol(atom)()
            elif isinstance(atom, int):
                atom = QueryElement.from_atomic_number(atom)()
            else:
                raise TypeError('QueryElement object expected')

        _map = super().add_atom(atom, _map, charge=charge, is_radical=is_radical, xy=xy)
        self._neighbors[_map] = neighbors
        self._hybridization[_map] = hybridization
        self._bonds_stereo[_map] = {}
        return _map

    def add_bond(self, n, m, bond: Union['molecule.Bond', int]):
        if not isinstance(bond, molecule.Bond):
            bond = molecule.Bond(bond)
        super().add_bond(n, m, bond)

        sbs = self._bonds_stereo
        if self._atoms[n].atomic_number != 1:  # not hydrogen
            try:  # remove stereo marks on bonded atoms and all its bonds
                del self._atoms_stereo[m]
            except KeyError:
                pass
            if sbs[m]:
                for x in sbs[m]:
                    del sbs[x][m]  # remove incoming
                sbs[m] = {}  # remove outgoing
        if self._atoms[m].atomic_number != 1:  # not hydrogen
            try:  # remove atom stereo state
                del self._atoms_stereo[n]
            except KeyError:
                pass
            if sbs[n]:
                for x in sbs[n]:
                    del sbs[x][n]
                sbs[n] = {}

    def delete_atom(self, n):
        isnt_hydrogen = self._atoms[n].atomic_number != 1
        super().delete_atom(n)

        del self._neighbors[n]
        del self._hybridization[n]

        sas = self._atoms_stereo
        sbs = self._bonds_stereo
        if isnt_hydrogen:
            # remove stereo marks on deleted atoms and all its neighbors
            try:
                del sas[n]
            except KeyError:
                pass
            for m in sbs.pop(n):
                del sbs[m][n]
                try:
                    del sas[m]
                except KeyError:
                    pass

    def delete_bond(self, n, m):
        super().delete_bond(n, m)
        sbs = self._bonds_stereo

        if self._atoms[n].atomic_number != 1:
            # remove stereo marks on unbonded atoms and all its bonds
            try:
                del self._atoms_stereo[m]
            except KeyError:
                pass
            if sbs[m]:
                for x in sbs[m]:
                    del sbs[x][m]
                sbs[m] = {}
        if self._atoms[m].atomic_number != 1:
            try:
                del self._atoms_stereo[n]
            except KeyError:
                pass
            if sbs[n]:
                for x in sbs[n]:
                    del sbs[x][n]
                sbs[n] = {}

    def remap(self, mapping, *, copy=False) -> 'QueryContainer':
        h = super().remap(mapping, copy=copy)
        mg = mapping.get
        sn = self._neighbors
        sbs = self._bonds_stereo

        if copy:
            hn = h._neighbors
            hh = h._hybridization
            has = h._atoms_stereo
            hbs = h._bonds_stereo
        else:
            hn = {}
            hh = {}
            has = {}
            hbs = {}

        for n, hyb in self._hybridization.items():
            m = mg(n, n)
            hn[m] = sn[n]
            hh[m] = hyb
            hbs[m] = {mg(x, x): s for x, s in sbs[n].items()}

        for n, stereo in self._atoms_stereo.items():
            has[mg(n, n)] = stereo

        if copy:
            return h

        self._neighbors = hn
        self._hybridization = hh
        self._atoms_stereo = has
        self._bonds_stereo = hbs
        return self

    def copy(self, *, meta=True) -> 'QueryContainer':
        copy = super().copy(meta=meta)
        copy._neighbors = self._neighbors.copy()
        copy._hybridization = self._hybridization.copy()
        copy._atoms_stereo = self._atoms_stereo.copy()
        copy._bonds_stereo = {n: s.copy() for n, s in self._bonds_stereo.items()}
        return copy

    def substructure(self, atoms, *, meta=False) -> 'QueryContainer':
        """
       create substructure containing atoms from atoms list

       :param atoms: list of atoms numbers of substructure
       :param meta: if True metadata will be copied to substructure
       """
        sub, atoms = super().substructure(atoms, meta=meta, sub=self.__class__)
        sa = self._atoms
        sb = self._bonds
        sn = self._neighbors
        sh = self._hybridization

        sub._neighbors = {n: sn[n] for n in atoms}
        sub._hybridization = {n: sh[n] for n in atoms}

        lost = {n for n, a in sa.items() if a.atomic_number != 1} - set(atoms)  # atoms not in substructure
        not_skin = {n for n in atoms if lost.isdisjoint(sb[n])}
        sub._atoms_stereo = {n: s for n, s in self._atoms_stereo.items() if n in not_skin}
        sub._bonds_stereo = cbs = {n: {} for n in atoms}
        for n, m_stereo in self._bonds_stereo.items():
            if n in not_skin:
                ns = cbs[n]
                for m, s in m_stereo.items():
                    if m in not_skin:
                        ns[m] = s

        sub._atoms = ca = {}
        for n in atoms:
            ca[n] = atom = sa[n].copy()
            atom._attach_to_graph(sub, n)
        return sub

    def union(self, other) -> 'QueryContainer':
        if isinstance(other, (QueryContainer, molecule.MoleculeContainer)):
            u = super().union(other)
            if isinstance(other, QueryContainer):
                u._neighbors.update(other._neighbors)
                u._hybridization.update(other._hybridization)

                ua = u._atoms
                for n, atom in other._atoms.items():
                    ua[n] = atom = atom.copy()
                    atom._attach_to_graph(u, n)
            else:
                un = u._neighbors
                uh = u._hybridization
                oh = u._hybridization
                for n, m in other._neighbors:
                    un[n] = (m,)
                    uh[n] = (oh[n],)

                ua = u._atoms
                for n, atom in other._atoms.items():
                    ua[n] = atom = QueryElement.from_atomic_number(atom.atomic_number)(atom.isotope)
                    atom._attach_to_graph(u, n)

            ub = u._bonds
            for n in other._bonds:
                ub[n] = {}
            seen = set()
            for n, m_bond in other._bonds.items():
                seen.add(n)
                for m, bond in m_bond.items():
                    if m not in seen:
                        ub[n][m] = ub[m][n] = bond.copy()

            u._atoms_stereo.update(other._atoms_stereo)
            us = u._bonds_stereo
            for n, m_stereo in other._bonds_stereo.items():
                us[n] = m_stereo.copy()
            return u
        elif isinstance(other, cgr.CGRContainer):
            raise TypeError('QueryContainer and CGRContainer unite impossible')
        elif isinstance(other, Graph):
            return other.union(self)
        else:
            raise TypeError('Graph expected')

    def __getstate__(self):
        return {'atoms_stereo': self._atoms_stereo, 'bonds_stereo': self._bonds_stereo, 'neighbors': self._neighbors,
                'hybridization': self._hybridization, **super().__getstate__()}

    def __setstate__(self, state):
        super().__setstate__(state)
        self._atoms_stereo = state['atoms_stereo']
        self._bonds_stereo = state['bonds_stereo']
        self._neighbors = state['neighbors']
        self._hybridization = state['hybridization']


__all__ = ['QueryContainer']
