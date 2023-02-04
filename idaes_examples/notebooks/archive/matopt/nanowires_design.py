#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES), and is copyright (c) 2018-2022
# by the software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia University
# Research Corporation, et al.  All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and
# license information.
#################################################################################
import numpy as np
from idaes.apps.matopt import *
from copy import deepcopy


if __name__ == '__main__':
    IAD = 3.7265
    orientation = '0001'
    nAtomRadius = 6
    nAtomUnitLength = 2
    origin = np.zeros(3, dtype=float)
    axisDirection = np.array([0, 0, 1], dtype=float)

    sizeUnitLength = 216
    coreRatio = 0.2
    p = -0.22479870084561238
    q = -0.9092660150083058
    alpha = -0.3684513
    CNBounds = (0, 4)
    BPs = list(range(CNBounds[0], CNBounds[1] + 1))
    Vals = [(p * pow(cn, 1 - alpha) - q * cn) for cn in BPs]

    lattice = WurtziteLattice.alignedWith(IAD, orientation)
    radius = lattice.getShellSpacing(orientation) * (nAtomRadius - 1)
    height = lattice.getLayerSpacing(orientation) * lattice.getUniqueLayerCount(orientation) * nAtomUnitLength
    shape = Cylinder(origin, radius, height, axisDirection)
    shape.shift(-0.001 * shape.Vh)  # shift downwards so that the seed is in the shape
    canvas = Canvas.fromLatticeAndShape(lattice, shape)
    tiling = LinearTiling.fromCylindricalShape(shape)
    canvas.makePeriodic(tiling, lattice.getNeighbors)
    # design = Design(canvas)
    # lattice.setDesign(design, Atom('In'), Atom('As'))
    # design.toPDB('canvas.pdb')

    CoreLayers = [i for i, p in enumerate(canvas.Points) if p[0] ** 2 + p[1] ** 2 < (coreRatio * radius) ** 2]
    CanvasMinusCoreLayers = [i for i, p in enumerate(canvas.Points) if i not in CoreLayers]
    NeighborsInside = [[j for j in canvas.NeighborhoodIndexes[i] if (
            j is not None and canvas.Points[j][0] ** 2 + canvas.Points[j][1] ** 2 <
            p[0] ** 2 + p[1] ** 2 - DBL_TOL)] for i, p in enumerate(canvas.Points)]

    m = MatOptModel(canvas, [Atom('')])

    m.Yi.rules.append(FixedTo(1, sites=CoreLayers))
    m.Yi.rules.append(ImpliesNeighbors(concs=(m.Yi, GreaterThan(1)),
                                       sites=CanvasMinusCoreLayers,
                                       neighborhoods=NeighborsInside))
    m.addSitesDescriptor('Vi', bounds=(min(Vals), max(Vals)),
                         rules=PiecewiseLinear(values=Vals, breakpoints=BPs, input_desc=m.Ci, con_type='UB'))
    m.addGlobalDescriptor('Ecoh', rules=EqualTo(SumSites(desc=m.Vi,coefs=(1.0 / sizeUnitLength))))
    m.addGlobalDescriptor('Size', bounds=(sizeUnitLength, sizeUnitLength), rules=EqualTo(SumSites(desc=m.Yi)))

    optimalDesign = None
    try:
        optimalDesign = m.maximize(m.Ecoh, tilim=360, solver='cplex')
    except:
        print('MaOpt can not find usable solver (CPLEX or NEOS-CPLEX)')
    
    if optimalDesign is not None:
        for i, p in enumerate(optimalDesign.Canvas.Points):
            if optimalDesign.Contents[i] is not None:
                if lattice.isASite(p):
                    optimalDesign.setContent(i, Atom('In'))
                elif lattice.isBSite(p):
                    optimalDesign.setContent(i, Atom('As'))
        optimalDesign.toPDB('result.pdb')
        periodicDesign = deepcopy(optimalDesign)
        for k in range(4):
            for i, p in enumerate(optimalDesign.Canvas.Points):
                periodicDesign.add(p + (k + 1) * shape.Vh, optimalDesign.Contents[i])
        for k in range(4):
            for i, p in enumerate(optimalDesign.Canvas.Points):
                periodicDesign.add(p - (k + 1) * shape.Vh, optimalDesign.Contents[i])
        periodicDesign.toPDB('periodic_result.pdb')
