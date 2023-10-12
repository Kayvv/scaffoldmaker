"""
Utility class for representing surfaces on which features can be located.
"""

import copy
from enum import Enum
import math
from cmlibs.maths.vectorops import cross, dot, magnitude, mult, normalize, sub
from cmlibs.utils.zinc.general import ChangeManager
from cmlibs.utils.zinc.field import find_or_create_field_coordinates, find_or_create_field_group
from cmlibs.utils.zinc.finiteelement import get_maximum_element_identifier, get_maximum_node_identifier
from cmlibs.zinc.element import Element, Elementbasis
from cmlibs.zinc.field import Field, FieldGroup
from cmlibs.zinc.node import Node
from scaffoldmaker.utils.interpolation import computeCubicHermiteArcLength, evaluateCoordinatesOnCurve, \
    getCubicHermiteArcLength, getCubicHermiteBasis, getCubicHermiteBasisDerivatives, \
    incrementXiOnLine, interpolateCubicHermite, \
    interpolateHermiteLagrangeDerivative, interpolateLagrangeHermiteDerivative, sampleCubicHermiteCurves, \
    sampleCubicHermiteCurvesSmooth, smoothCubicHermiteDerivativesLine, smoothCubicHermiteDerivativesLoop, \
    updateCurveLocationTofaceNumber
from scaffoldmaker.utils import vector


class TrackSurfacePosition:
    """
    Position on TrackSurface. Create with createPosition~ method of TrackSurface.
    """

    def __init__(self, e1, e2, xi1, xi2):
        """
        :param e1, e2: Element index in directions 1 and 2, starting at 0.
        :param xi1, xi2: 2-D element chart coordinates 0.0 <= xiN <= 1.0
        """
        self.e1 = e1
        self.e2 = e2
        self.xi1 = xi1
        self.xi2 = xi2

    def __str__(self):
        return 'element (' + str(self.e1) + ',' + str(self.e2) + ') xi (' + str(self.xi1) + ',' + str(self.xi2) + ')'


class TrackSurface:
    """
    A surface description on which positions can be stored and tracked for
    specified directions and distances for location surface features.
    Currently represented by a lattice of elementsCount1 x elementsCount2
    square elements with bicubic Hermite interpolation but zero cross derivatives.
    """

    def __init__(self, elementsCount1, elementsCount2, nx, nd1, nd2, nd12=None, loop1=False):
        """
        Creates a TrackSurface with a lattice of elementsCount1*elementsCount2
        elements, with nodes and elements varying across direction 1 fastest.
        :param elementsCount1, elementsCount2: Number of elements in directions 1 and 2.
        :param nx: List of (elementsCount2 + 1)*(elementsCount1 + 1) node coordinates, 3 component.
        :param nd1: List of node derivatives in direction 1.
        :param nd2: List of node derivatives in direction 2.
        :param nd12: Optional list of node cross derivatives in directions 1, 2.
        coordinates, derivatives 1 and derivatives 2. Cross derivatives are zero.
        All coordinates are 3 component.
        :param loop1: Set to True if loops back to start in direction 1. Supply
        one fewer node around direction 1.
        """
        self._elementsCount1 = elementsCount1
        self._elementsCount2 = elementsCount2
        self._nx = nx
        self._nd1 = nd1
        self._nd2 = nd2
        self._nd12 = nd12
        self._loop1 = loop1
        # get max range for tolerances
        self._xMin = copy.copy(nx[0])
        self._xMax = copy.copy(nx[0])
        for x in nx:
            for c in range(3):
                s = x[c]
                if s < self._xMin[c]:
                    self._xMin[c] = s
                elif s > self._xMax[c]:
                    self._xMax[c] = s
        self._xRange = [self._xMax[c] - self._xMin[c] for c in range(3)]

    def createMirrorX(self):
        """
        Mirror track surface about x axis by negating all x coordinates
        and rewind elements by flipping order and derivatives in direction 1.
        :return: TrackSurface
        """
        nx = []
        nd1 = []
        nd2 = []
        if self._nd12:
            print("TrackSurface.createMirrorX.  Implementation for cross derivatives not checked")
        nd12 = [] if self._nd12 else None
        nodesCount1 = self._elementsCount1 + (0 if self._loop1 else 1)
        nodesCount2 = self._elementsCount2 + 1
        for n2 in range(nodesCount2):
            for n1 in range(nodesCount1):
                oi = n2*nodesCount1 + self._elementsCount1 - n1
                ox = copy.deepcopy(self._nx[oi])
                od1 = copy.deepcopy(self._nd1[oi])
                od2 = copy.deepcopy(self._nd2[oi])
                nx.append([-ox[0],  ox[1],  ox[2]])
                nd1.append([od1[0], -od1[1], -od1[2]])
                nd2.append([-od2[0], od2[1], od2[2]])
                if nd12:
                    od12 = copy.deepcopy(self._nd12[oi])
                    nd12.append([od12[0], od12[1], od12[2]])  # need to check
        return TrackSurface(self._elementsCount1, self._elementsCount2, nx, nd1, nd2, nd12, loop1=self._loop1)

    def createPositionProportion(self, proportion1, proportion2):
        """
        Return position on surface for proportions across directions 1 and 2.
        :param proportion1, proportion2: Proportions across directions 1 and 2,
        each varying from 0.0 to 1.0 (or 2.0 if loop1), with elements equal sized.
        :return: TrackSurfacePosition
        """
        maxProportion1 = 2.0 if self._loop1 else 1.0
        assert (proportion1 >= 0.0) and (proportion1 <= maxProportion1), \
            'createPositionProportion:  Proportion 1 (' + str(proportion1) + ') out of range'
        assert (proportion2 >= 0.0) and (proportion2 <= 1.0), \
            'createPositionProportion:  Proportion 2 (' + str(proportion2) + ') out of range'

        pe1 = proportion1 * self._elementsCount1
        max_e1 = 2 * self._elementsCount1 if self._loop1 else self._elementsCount1
        if pe1 < max_e1:
            e1 = int(pe1)
            xi1 = pe1 - e1
        else:
            e1 = max_e1 - 1
            xi1 = 1.0
        pe2 = proportion2 * self._elementsCount2
        if pe2 < self._elementsCount2:
            e2 = int(pe2)
            xi2 = pe2 - e2
        else:
            e2 = self._elementsCount2 - 1
            xi2 = 1.0
        return TrackSurfacePosition(e1, e2, xi1, xi2)

    def getProportion(self, position):
        """
        From a position on this track surface, return proportions.
        :return: proportion1, proportion2
        """
        return [(position.e1 + position.xi1) / self._elementsCount1,
                (position.e2 + position.xi2) / self._elementsCount2]

    def evaluateCoordinates(self, position: TrackSurfacePosition, derivatives=False):
        """
        Evaluate coordinates on surface at position, and optionally
        derivative w.r.t. xi1 and xi2.
        :param position: A valid TrackSurfacePosition.
        :param derivatives: Set to True to calculate and return derivatives w.r.t. element xi.
        :return: If derivatives is False: coordinates [x, y, z].
        If derivatives is True: coordinates, derivative1, derivative2.
        """
        nodesCount1 = self._elementsCount1 if self._loop1 else self._elementsCount1 + 1
        e1 = position.e1 % self._elementsCount1  # to handle loop1
        nx = self._nx
        nd1 = self._nd1
        nd2 = self._nd2
        nd12 = self._nd12
        nid0 = position.e2 * nodesCount1
        n1 = nid0 + e1
        n2 = nid0 if (self._loop1 and ((e1 + 1) == self._elementsCount1)) else n1 + 1
        n3 = n1 + nodesCount1
        n4 = n2 + nodesCount1
        nid = [n1, n2, n3, n4]
        f1x1, f1d1, f1x2, f1d2 = getCubicHermiteBasis(position.xi1)
        f2x1, f2d1, f2x2, f2d2 = getCubicHermiteBasis(position.xi2)
        fx  = [f1x1*f2x1, f1x2*f2x1, f1x1*f2x2, f1x2*f2x2]
        fd1 = [f1d1*f2x1, f1d2*f2x1, f1d1*f2x2, f1d2*f2x2]
        fd2 = [f1x1*f2d1, f1x2*f2d1, f1x1*f2d2, f1x2*f2d2]
        fd12 = [f1d1*f2d1, f1d2*f2d1, f1d1*f2d2, f1d2*f2d2] if nd12 else None
        coordinates = []
        for c in range(3):
            x = 0.0
            for ln in range(4):
                gn = nid[ln]
                x += fx[ln]*nx[gn][c] + fd1[ln]*nd1[gn][c] + fd2[ln]*nd2[gn][c]
                if nd12:
                    x += fd12[ln] * nd12[gn][c]
            coordinates.append(x)
        if not derivatives:
            return coordinates
        df1x1, df1d1, df1x2, df1d2 = getCubicHermiteBasisDerivatives(position.xi1)
        d1fx  = [df1x1*f2x1, df1x2*f2x1, df1x1*f2x2, df1x2*f2x2]
        d1fd1 = [df1d1*f2x1, df1d2*f2x1, df1d1*f2x2, df1d2*f2x2]
        d1fd2 = [df1x1*f2d1, df1x2*f2d1, df1x1*f2d2, df1x2*f2d2]
        d1fd12 = [df1d1*f2d1, df1d2*f2d1, df1d1*f2d2, df1d2*f2d2] if nd12 else None
        df2x1, df2d1, df2x2, df2d2 = getCubicHermiteBasisDerivatives(position.xi2)
        d2fx  = [f1x1*df2x1, f1x2*df2x1, f1x1*df2x2, f1x2*df2x2]
        d2fd1 = [f1d1*df2x1, f1d2*df2x1, f1d1*df2x2, f1d2*df2x2]
        d2fd2 = [f1x1*df2d1, f1x2*df2d1, f1x1*df2d2, f1x2*df2d2]
        d2fd12 = [f1d1*df2d1, f1d2*df2d1, f1d1*df2d2, f1d2*df2d2] if nd12 else None
        derivative1 = []
        derivative2 = []
        for c in range(3):
            d1 = 0.0
            d2 = 0.0
            for ln in range(4):
                gn = nid[ln]
                d1 += d1fx[ln]*nx[gn][c] + d1fd1[ln]*nd1[gn][c] + d1fd2[ln]*nd2[gn][c]
                d2 += d2fx[ln]*nx[gn][c] + d2fd1[ln]*nd1[gn][c] + d2fd2[ln]*nd2[gn][c]
                if nd12:
                    d1 += d1fd12[ln]*nd12[gn][c]
                    d2 += d2fd12[ln]*nd12[gn][c]
            derivative1.append(d1)
            derivative2.append(d2)
        return coordinates, derivative1, derivative2

    class HermiteCurveMode(Enum):
        SMOOTH = 1    # smooth variation of element size between end derivatives
        TRANSITION_END = 2  # transition from start derivative then even size
        TRANSITION_START = 3  # even size then transition to end derivative
        TRANSITION_START_AND_END = 3  # transition to/from start and end derivatives and even size in between
        UNIFORM_SIZE = 4  # regardless of initial derivatives, sample in even sizes

    def createHermiteCurvePoints(self, aProportion1, aProportion2, bProportion1, bProportion2, elementsCount,
            derivativeStart=None, derivativeEnd=None, curveMode = HermiteCurveMode.SMOOTH):
        """
        Create hermite curve points between two points a and b on the surface, each defined
        by their proportions over the surface in directions 1 and 2.
        Also returns cross direction 2 in plane of surface with similar magnitude to curve derivative 1,
        and unit surface normals.
        :param derivativeStart, derivativeEnd: Optional derivative vectors in 3-D world coordinates
        to match at the start and end of the curves. If omitted, fits in with other derivative or is
        in a straight line from a to b.
        :param elementsCount:  Number of elements out.
        :return: nx[], nd1[], nd2[], nd3[], nProportions[]
        """
        #print('createHermiteCurvePoints', aProportion1, aProportion2, bProportion1, bProportion2, elementsCount, derivativeStart, derivativeEnd)
        if derivativeStart:
            position = self.createPositionProportion(aProportion1, aProportion2)
            _, sd1, sd2 = self.evaluateCoordinates(position, derivatives = True)
            delta_xi1, delta_xi2 = calculate_surface_delta_xi(sd1, sd2, derivativeStart)
            dp1Start = delta_xi1 / self._elementsCount1
            dp2Start = delta_xi2 / self._elementsCount2
            derivativeMagnitudeStart = math.sqrt(dp1Start*dp1Start + dp2Start*dp2Start)
            dp1Start *= elementsCount
            dp2Start *= elementsCount
            #print('start delta_xi1', delta_xi1, 'delta_xi2', delta_xi2)
            #print('dp1Start', dp1Start, 'dp2Start', dp2Start)
        if derivativeEnd:
            position = self.createPositionProportion(bProportion1, bProportion2)
            _, sd1, sd2 = self.evaluateCoordinates(position, derivatives = True)
            delta_xi1, delta_xi2 = calculate_surface_delta_xi(sd1, sd2, derivativeEnd)
            dp1End = delta_xi1 / self._elementsCount1
            dp2End = delta_xi2 / self._elementsCount2
            derivativeMagnitudeEnd = math.sqrt(dp1End*dp1End + dp2End*dp2End)
            dp1End *= elementsCount
            dp2End *= elementsCount
            #print('end delta_xi1', delta_xi1, 'delta_xi2', delta_xi2)
            #print('dp1End', dp1End, 'dp2End', dp2End)
        if not derivativeStart:
            if derivativeEnd:
                dp1Start, dp2Start = interpolateLagrangeHermiteDerivative([ aProportion1, aProportion2 ], [ bProportion1, bProportion2 ], [ dp1End, dp2End ], 0.0)
            else:
                dp1Start = bProportion1 - aProportion1
                dp2Start = bProportion2 - aProportion2
            derivativeMagnitudeStart = math.sqrt(dp1Start*dp1Start + dp2Start*dp2Start)/elementsCount
        if not derivativeEnd:
            if derivativeStart:
                dp1End, dp2End = interpolateHermiteLagrangeDerivative([ aProportion1, aProportion2 ], [ dp1Start, dp2Start ], [ bProportion1, bProportion2 ], 1.0)
            else:
                dp1End = bProportion1 - aProportion1
                dp2End = bProportion2 - aProportion2
            derivativeMagnitudeEnd = math.sqrt(dp1End*dp1End + dp2End*dp2End)/elementsCount
        #print('derivativeMagnitudeStart', derivativeMagnitudeStart, 'derivativeMagnitudeEnd', derivativeMagnitudeEnd)
        proportions, dproportions = sampleCubicHermiteCurvesSmooth(
            [[aProportion1, aProportion2], [bProportion1, bProportion2]],
            [[dp1Start, dp2Start], [dp1End, dp2End]],
            elementsCount, derivativeMagnitudeStart, derivativeMagnitudeEnd)[0:2]
        if curveMode != self.HermiteCurveMode.SMOOTH:
            if derivativeStart and (curveMode in [self.HermiteCurveMode.TRANSITION_START, self.HermiteCurveMode.TRANSITION_START_AND_END]):
                addLengthStart = 0.5*derivativeMagnitudeStart
                lengthFractionStart = 0.5
            else:
                addLengthStart = 0.0
                lengthFractionStart = 1.0
            if derivativeEnd and (curveMode in [self.HermiteCurveMode.TRANSITION_END, self.HermiteCurveMode.TRANSITION_START_AND_END]):
                addLengthEnd = 0.5*derivativeMagnitudeEnd
                lengthFractionEnd = 0.5
            else:
                addLengthEnd = 0.0
                lengthFractionEnd = 1.0
            proportions, dproportions = sampleCubicHermiteCurves(
                proportions, dproportions, elementsCount,
                addLengthStart, addLengthEnd, lengthFractionStart, lengthFractionEnd)[0:2]
        #print(' proportions', proportions)
        #print('dproportions', dproportions)
        nx  = []
        nd1 = []
        nd2 = []
        nd3 = []
        for n in range(0, elementsCount + 1):
            position = self.createPositionProportion(proportions[n][0], proportions[n][1])
            x, sd1, sd2 = self.evaluateCoordinates(position, derivatives = True)
            f1 = dproportions[n][0] * self._elementsCount1
            f2 = dproportions[n][1] * self._elementsCount2
            d1 = [ (f1*sd1[c] + f2*sd2[c]) for c in range(3) ]
            d3 = vector.crossproduct3(sd1, sd2)
            # handle zero magnitude of d3
            mag = math.sqrt(sum(d3[c]*d3[c] for c in range(3)))
            if mag > 0.0:
                d3 = [ (d3[c]/mag) for c in range(3) ]
            d2 = vector.crossproduct3(d3, d1)
            nx .append(x)
            nd2.append(d2)
            nd1.append(d1)
            nd3.append(d3)
        #print('createHermiteCurvePoints end \n nx', nx,'\nnd1',nd1,'\nnd2',nd2,'\nnd3',nd3)
        return nx, nd1, nd2, nd3, proportions

    def resampleHermiteCurvePointsSmooth(self, nx, nd1, nd2, nd3, nProportions, derivativeMagnitudeStart=None, derivativeMagnitudeEnd=None):
        """
        Call sampleCubicHermiteCurvesSmooth on nx, nd1 and recalculate positions, nd2, nd3 for points.
        :return: nx[], nd1[], nd2[], nd3[], nProportions[]
        """
        elementsCount = len(nx) - 1
        #print(nx, nd1, elementsCount, derivativeMagnitudeStart, derivativeMagnitudeEnd)
        nx, nd1 = sampleCubicHermiteCurvesSmooth(nx, nd1, elementsCount, derivativeMagnitudeStart, derivativeMagnitudeEnd)[0:2]
        mag2 = vector.magnitude(nd2[0])
        if mag2 > 0.0:
            nd2[0] = vector.setMagnitude(nd2[0], vector.magnitude(nd1[0]))
        for n in range(1, elementsCount):
            p = self.findNearestPosition(nx[n], self.createPositionProportion(*nProportions[n]))
            nProportions[n] = self.getProportion(p)
            _, sd1, sd2 = self.evaluateCoordinates(p, derivatives=True)
            _, d2, d3 = calculate_surface_axes(sd1, sd2, vector.normalise(nd1[n]))
            nd2[n] = vector.setMagnitude(d2, vector.magnitude(nd1[n]))
            nd3[n] = d3
        mag2 = vector.magnitude(nd2[-1])
        if mag2 > 0.0:
            nd2[-1] = vector.setMagnitude(nd2[-1], vector.magnitude(nd1[-1]))
        return nx, nd1, nd2, nd3, nProportions

    def _positionOnBoundary(self, position: TrackSurfacePosition):
        """
        :param position:
        :return: 1 if on xi1 boundary, 2 if on xi2 boundary, 0 if not on a boundary.
        """
        LOWER_P_LIMIT = 1.0E-7
        UPPER_P_LIMIT = 1.0 - LOWER_P_LIMIT
        if not self._loop1:
            proportion1 = (position.e1 + position.xi1) / self._elementsCount1
            if (proportion1 < LOWER_P_LIMIT) or (proportion1 > UPPER_P_LIMIT):
                return 1
        proportion2 = (position.e2 + position.xi2) / self._elementsCount2
        if (proportion2 < LOWER_P_LIMIT) or (proportion2 > UPPER_P_LIMIT):
            return 2
        return 0

    def _advancePosition(self, startPosition, dxi1, dxi2, MAX_MAG_DXI=0.5):
        """
        Advance position by element delta xi to maximum change of xi coordinates or boundary.
        :param startPosition: Start position.
        :param dxi1: Increment in xi1.
        :param dxi2: Increment in xi2.
        :param MAX_MAG_DXI: Maximum magnitude of dxi to keep increments reasonable for a cubic curve.
        :return: Advanced position, onBoundary (0/1=xi1/2=xi2), actual dxi1, actual dxi2
        """
        startProportion1, startProportion2 = self.getProportion(startPosition)
        magDxi = magnitude([dxi1, dxi2])
        if magDxi > MAX_MAG_DXI:
            factor = MAX_MAG_DXI / magDxi
            dxi1 *= factor
            dxi2 *= factor
        proportion1 = startProportion1 + dxi1 / self._elementsCount1
        proportion2 = startProportion2 + dxi2 / self._elementsCount2
        onBoundary = 0
        if self._loop1:
            if proportion1 < 0.0:
                proportion1 += 1.0
            elif proportion1 > 2.0:
                proportion1 -= 2.0
        else:
            if proportion1 < 0.0:
                proportion1 = 0.0
                onBoundary = 1
            elif proportion1 > 1.0:
                proportion1 = 1.0
                onBoundary = 1
        if proportion2 < 0.0:
            proportion2 = 0.0
            onBoundary = 2
        elif proportion2 > 1.0:
            proportion2 = 1.0
            onBoundary = 2
        if onBoundary:
            if not self._loop1:
                dxi1 = (proportion1 - startProportion1) / self._elementsCount1
            dxi2 = (proportion2 - startProportion2) / self._elementsCount2
        return self.createPositionProportion(proportion1, proportion2), onBoundary, dxi1, dxi2

    def findIntersectionPoint(self, otherTrackSurface,
                              startPosition: TrackSurfacePosition,
                              otherStartPosition: TrackSurfacePosition):
        """
        Find an intersection point on both self and otherTrackSurface from an initial guess.
        :param otherTrackSurface: Other TrackSurface to find intersection with.
        :param startPosition: Start position to get intersection point near to.
        Needs to be a good guess if surface has complex curvature.
        :param otherStartPosition: Initial estimate of nearest position on other TrackSurface.
        Use findNearestParameterPosition if a better guess is not available.
        :return: TrackSurfacePosition, OtherTrackSurfacePosition, x, tangent, onBoundary (0/1=xi1/2=xi2)
        or None, None, None, None, 0  if no intersection found.
        The tangent is normalized n1 x n2, a unit vector along the intersection curve.
        """
        # print("findIntersectionPoint", startPosition)
        position = copy.deepcopy(startPosition)
        otherPosition = copy.deepcopy(otherStartPosition)
        MAX_MAG_DXI = 0.5  # target/maximum magnitude of xi increment
        XI_TOL = 1.0E-7
        X_TOL = 1.0E-6 * max(self._xRange)
        MAG_JOLT_DXI = 0.1  # magnitude of xi change when jolting out of local minimum
        mag_dxi = 0.0
        old_dxi = None
        mag_old_dxi = 0.0
        jolt_index = 0
        jolt_it = -2  # iter number of last jolt
        for it in range(100):
            onBoundary = self._positionOnBoundary(position)
            x, d1, d2 = self.evaluateCoordinates(position, derivatives=True)
            otherPosition = otherTrackSurface.findNearestPosition(x, otherPosition)
            onOtherBoundary = otherTrackSurface._positionOnBoundary(otherPosition)
            ox, od1, od2 = otherTrackSurface.evaluateCoordinates(otherPosition, derivatives=True)
            r = sub(ox, x)
            mag_r = magnitude(r)
            # print("iter", it + 1, "pos", position, onBoundary, "other", otherPosition, onOtherBoundary, "mag_r", mag_r)
            n1 = cross(d1, d2)
            if mag_r < X_TOL:
                n2 = cross(od1, od2)
                tangent = cross(n1, n2)
                if (magnitude(tangent) < 1.0E-6 * X_TOL) or (
                        (onBoundary == 2) and (onOtherBoundary == 2) and (dot(normalize(d1), normalize(od1)) > 0.9999)):
                    tangent = d1 if (onBoundary == 2) else d2
                tangent = normalize(tangent)
                # print("TrackSurface.findIntersectionPoint found intersection: ", position, "mag_r", mag_r, "iter", it + 1)
                return position, otherPosition, x, tangent, onBoundary
            od = None
            if onOtherBoundary and not onBoundary:
                # projection is normal to this surface, not normal to other surface/edge
                od = od1 if (onOtherBoundary == 2) else od2
                n = cross(cross(od, r), od)
                if dot(n, n1) < 0.0:
                    n = [-s for s in n]
            # this may be useful in future for tracking along boundary
            # elif onBoundary:
            #     d = d1 if (onBoundary == 2) else d2
            #     n = cross(cross(d, r), d)
            #     if dot(n, n1) < 0.0:
            #         n = [-s for s in n]
            n = normalize(n1)
            r_dot_n = dot(r, n)
            if r_dot_n < 0:
                # flip normal to be towards other x
                n = [-s for s in n]
                r_dot_n = -r_dot_n
            r_out_of_plane = mult(n, r_dot_n)
            r_in_plane = sub(r, r_out_of_plane)
            if onOtherBoundary and onBoundary:
                u = r_in_plane
            else:
                # add out-of-plane slope component
                mag_ri = magnitude(r_in_plane)
                if mag_ri == 0.0:
                    u = [0.0, 0.0, 0.0]
                else:
                    # slope_factor = mag_r / mag_ri
                    slope_factor = mag_r * mag_r / (mag_ri * mag_ri)
                    # print("    slope_factor", slope_factor)
                    # if slope_factor > 1000.0:
                    #     slope_factor = 1000.0
                    u = mult(r_in_plane, slope_factor)
                    if onOtherBoundary and not onBoundary:
                        # remove components of u not parallel to other boundary
                        u_od2_alignment = dot(normalize(u), normalize(od2))
                        if (it == (jolt_it + 1)) or (u_od2_alignment > 0.99):
                            new_u = vector.vectorProjection(u, od2)
                            # print("    other fix:", u_od2_alignment, "/", u, "-->", new_u)
                            u = new_u
            dxi1, dxi2 = calculate_surface_delta_xi(d1, d2, u)
            dxi = [dxi1, dxi2]
            mag_dxi = magnitude(dxi)
            # print("     dxi", dxi1, dxi2)
            if mag_dxi < (100.0 * XI_TOL):
                jolt_it = it
                # slow progress: may be a local minimum; jolt along boundary edge or cardinal direction
                if onBoundary and ((not onOtherBoundary) or (jolt_index % 4 < 2)):
                    jolt_case = jolt_index % 2
                    jolt_dxi1 = 0.0 if (onBoundary == 1) else -MAG_JOLT_DXI if (jolt_case == 0) else MAG_JOLT_DXI
                    jolt_dxi2 = 0.0 if (onBoundary == 2) else -MAG_JOLT_DXI if (jolt_case == 0) else MAG_JOLT_DXI
                    jolt_position, _, jolt_dxi1, jolt_dxi2 = self._advancePosition(position, jolt_dxi1, jolt_dxi2)
                elif onOtherBoundary:
                    jolt_case = jolt_index % 2
                    jolt_other_dxi1 = 0.0 if (onOtherBoundary == 1) else \
                        -MAG_JOLT_DXI if (jolt_case == 0) else MAG_JOLT_DXI
                    jolt_other_dxi2 = 0.0 if (onOtherBoundary == 2) else \
                        -MAG_JOLT_DXI if (jolt_case == 0) else MAG_JOLT_DXI
                    jolt_otherPosition, _, jolt_other_dxi1, jolt_other_dxi2 = self._advancePosition(
                        otherPosition, jolt_other_dxi1, jolt_other_dxi2)
                    if (jolt_other_dxi1 != 0.0) or (jolt_other_dxi2 != 0.0):
                        jolt_other_x = otherTrackSurface.evaluateCoordinates(jolt_otherPosition)
                        jolt_position = self.findNearestPosition(jolt_other_x, position)
                        proportion = self.getProportion(position)
                        jolt_proportion = self.getProportion(jolt_position)
                        jolt_dxi1 = (jolt_proportion[0] - proportion[0]) * self._elementsCount1
                        jolt_dxi2 = (jolt_proportion[1] - proportion[1]) * self._elementsCount2
                    else:
                        jolt_position = position
                        jolt_dxi1 = 0.0
                        jolt_dxi2 = 0.0
                else:
                    jolt_case = jolt_index % 4
                    jolt_dxi1 = -MAG_JOLT_DXI if (jolt_case == 0) else MAG_JOLT_DXI if (jolt_case == 2) else 0.0
                    jolt_dxi2 = -MAG_JOLT_DXI if (jolt_case == 1) else MAG_JOLT_DXI if (jolt_case == 3) else 0.0
                    jolt_position, _, jolt_dxi1, jolt_dxi2 = \
                        self._advancePosition(position, jolt_dxi1, jolt_dxi2, MAX_MAG_DXI=MAX_MAG_DXI)
                if (jolt_dxi1 != 0.0) or (jolt_dxi2 != 0.0):
                    jolt_x, jolt_d1, jolt_d2 = self.evaluateCoordinates(jolt_position, derivatives=True)
                    jolt_otherPosition = otherTrackSurface.findNearestPosition(jolt_x, otherPosition)
                    jolt_ox = otherTrackSurface.evaluateCoordinates(jolt_otherPosition)
                    jolt_r = sub(jolt_ox, jolt_x)
                    jolt_n1 = normalize(cross(jolt_d1, jolt_d2))
                    r_dot_n_signed = dot(r, normalize(n1))
                    jolt_r_dot_n_signed = dot(jolt_r, jolt_n1)
                    if r_dot_n_signed * jolt_r_dot_n_signed <= 0.0:
                        # get linear crossing point
                        jolt_factor = abs(r_dot_n_signed) / (abs(r_dot_n_signed) + abs(jolt_r_dot_n_signed))
                        dxi1 = jolt_dxi1 * jolt_factor
                        dxi2 = jolt_dxi2 * jolt_factor
                        dxi = [dxi1, dxi2]
                        mag_dxi = magnitude(dxi)
                        # print("JOLT CROSS", jolt_case, "factor", jolt_factor, "dxi", dxi1, dxi2)
                    elif abs(jolt_r_dot_n_signed) < abs(r_dot_n_signed):
                        dxi1 = jolt_dxi1
                        dxi2 = jolt_dxi2
                        dxi = [dxi1, dxi2]
                        mag_dxi = magnitude(dxi)
                        # print("JOLT LOWER", jolt_case, "dxi", dxi1, dxi2)
                    else:
                        # print("JOLT IGNORE", jolt_case)
                        pass  # jolt did not help
                    jolt_index += 1
            elif old_dxi and (dot(dxi, old_dxi) < -0.5 * (mag_old_dxi * mag_old_dxi)):
                # control oscillations
                osc_factor = mag_dxi / (mag_dxi + mag_old_dxi)
                # print("    osc_factor", osc_factor)
                dxi1 *= osc_factor
                dxi2 *= osc_factor
                dxi = [dxi1, dxi2]
                mag_dxi *= osc_factor
            position, onBoundary, dxi1, dxi2 = self._advancePosition(position, dxi1, dxi2, MAX_MAG_DXI=MAX_MAG_DXI)
            old_dxi = dxi
            mag_old_dxi = mag_dxi
            # print("    adxi", dxi1, dxi2)
            mag_dxi = magnitude([dxi1, dxi2])
            if mag_dxi < XI_TOL:
                print("TrackSurface.findIntersectionPoint failed:  Insufficient increment, no intersection found")
                break
        else:
                print('TrackSurface.findIntersectionPoint failed:  Reached max iterations', it + 1,
                  'last increment', mag_dxi)
        return None, None, None, None, 0

    def findIntersectionCurve(self, otherTrackSurface, startPosition: TrackSurfacePosition=None,
                              MAX_MAG_DXI=0.5, curveElementsCount: int=8):
        """
        Find curve on intersection of self and otherTrackSurface nearest to start position.
        an intersection point on both self and otherTrackSurface from an initial guess.
        The curve is resampled to have equal sized elements along/around it.
        :param otherTrackSurface: Other TrackSurface to find intersection with.
        :param startPosition: Optional start position to get intersection point near to.
        Needs to be a good guess if surface has complex curvature. If not supplied, gets nearest parameter position.
        :param curveElementsCount: Number of elements to return in resampled curve.
        :return: cx[], cd1[], cProportions (on this surface), loop (True if curve is a closed loop),
        or None, None, None, False if no intersection.
        """
        # print("findIntersectionCurve", startPosition)
        if startPosition:
            nextPosition = startPosition
            startX = self.evaluateCoordinates(startPosition, derivatives=False)
            otherPosition = otherStartPosition = self.findNearestParameterPosition(startX)[0]
        else:
            n1Limit = self._elementsCount1 if self._loop1 else self._elementsCount1 + 1
            nearest_distance = None
            nearest_n1 = None
            nearest_n2 = None
            nearestOtherPosition = None
            p = 0
            for n2 in range(self._elementsCount2 + 1):
                for n1 in range(n1Limit):
                    targetx = self._nx[n2 * n1Limit + n1]
                    otherPosition, distance = otherTrackSurface.findNearestParameterPosition(targetx)
                    if (nearest_distance is None) or (distance < nearest_distance):
                        nearest_distance = distance
                        nearest_n1 = n1
                        nearest_n2 = n2
                        nearestOtherPosition = otherPosition
                    p += 1
            nextPosition = startPosition = self.createPositionProportion(
                nearest_n1 / self._elementsCount1, nearest_n2 / self._elementsCount2)
            otherPosition = otherStartPosition = nearestOtherPosition
        X_TOL = 1.0E-6 * max(self._xRange)
        px = []
        pd1 = []
        boundaryCount = 0
        loop = False
        xiLoopSamples = [0.25, 0.5, 0.75, 1.0]
        pointCount = 0
        crossBoundary = 0
        while True:
            position, otherPosition, x, t, onBoundary = \
                self.findIntersectionPoint(otherTrackSurface, nextPosition, otherPosition)
            if not position:
                assert pointCount == 0
                print("TrackSurface.findIntersectionCurve.  No intersection")
                return None, None, None, False
            onOtherBoundary = otherTrackSurface._positionOnBoundary(otherPosition)
            # print("  curve pos", position, "boundary", onBoundary, "onOtherBoundary", onOtherBoundary)
            if boundaryCount == 0:
                px.append(x)
                pd1.append(t)
            else:
                px.insert(0, x)
                pd1.insert(0, t)
            pointCount += 1
            if (pointCount > 1) and (onBoundary or onOtherBoundary) and \
                    (crossBoundary or not (onBoundary and onOtherBoundary)):
                if (pointCount > 1) and (magnitude(sub(x, px[-2])) < X_TOL):
                    px.pop()
                    pd1.pop()
                    pointCount -= 1
                boundaryCount += 1
                # print("=== Boundary", boundaryCount, startPosition)
                if boundaryCount == 2:
                    break
                # go in reverse from start positions
                position = startPosition
                otherPosition = otherStartPosition
                t = pd1[0]
            # check for loop; can't happen after a boundary had been found
            if (boundaryCount == 0) and (pointCount > 2):
                x1, d1 = px[-2], pd1[-2]
                x2, d2 = px[-1], pd1[-1]
                dscale = computeCubicHermiteArcLength(x1, d1, x2, d2, rescaleDerivatives=True)
                d1 = mult(d1, dscale)
                d2 = mult(d2, dscale)
                xi = 0.0
                for xi in xiLoopSamples:
                    tx = interpolateCubicHermite(x1, d1, x2, d2, xi)
                    delta = sub(tx, px[0])
                    distance = magnitude(delta)
                    if distance < (0.2 * dscale):
                        loop = True
                        break
                if loop:
                    # remove the last point as close to or past the start
                    px.pop()
                    pd1.pop()
                    pointCount -= 1
                    break
            x, d1, d2 = self.evaluateCoordinates(position, derivatives=True)
            dxi1, dxi2 = calculate_surface_delta_xi(d1, d2, mult(t, -1.0) if (boundaryCount == 1) else t)
            nextPosition, crossBoundary = self._advancePosition(position, dxi1, dxi2, MAX_MAG_DXI=MAX_MAG_DXI)[0:2]
            # print("  t", t, "next", nextPosition)

        # resample and re-find positions and tangents
        if loop:
            px.append(px[0])
            pd1.append(pd1[0])
        nx, nd1 = sampleCubicHermiteCurves(px, pd1, curveElementsCount, arcLengthDerivatives=True)[0:2]
        if loop:
            nx.pop()
            nd1.pop()
        cx = []
        cd1 = []
        cProportions = []
        for n in range(len(nx)):
            position = self.findNearestPosition(nx[n], position)
            position, otherPosition, x, t, onBoundary =\
                self.findIntersectionPoint(otherTrackSurface, position, otherPosition)
            cx.append(x)
            cd1.append(t)
            cProportions.append(self.getProportion(position))
        if loop:
            cd1 = smoothCubicHermiteDerivativesLoop(cx, cd1, fixAllDirections=True)
        else:
            cd1 = smoothCubicHermiteDerivativesLine(cx, cd1, fixAllDirections=True)
        return cx, cd1, cProportions, loop

    def findNearestParameterPosition(self, targetx: list):
        """
        Get position of x parameter nearest to targetx.
        Use to set a good starting point for findNearestPosition and findIntersectionPoint.
        :param targetx: Coordinates of point to find nearest to.
        :return: nearest TrackSurfacePosition, nearest distance
        """
        n1Limit = self._elementsCount1 if self._loop1 else self._elementsCount1 + 1
        p = 0
        nearest_distance = None
        nearest_n1 = None
        nearest_n2 = None
        for n2 in range(self._elementsCount2 + 1):
            for n1 in range(n1Limit):
                distance = magnitude(sub(self._nx[p], targetx))
                if (nearest_distance is None) or (distance < nearest_distance):
                    nearest_distance = distance
                    nearest_n1 = n1
                    nearest_n2 = n2
                p += 1
        return self.createPositionProportion(nearest_n1 / self._elementsCount1, nearest_n2 / self._elementsCount2), \
            nearest_distance

    def findNearestPosition(self, targetx: list, startPosition: TrackSurfacePosition=None) -> TrackSurfacePosition:
        """
        Find the nearest point to targetx on the track surface, with optional start position.
        Only works if track surface is simply shaped; use a close startPosition if not.
        :param targetx:  Coordinates of point to find nearest to.
        :param startPosition: Optional initial track surface position.
        :return: Nearest TrackSurfacePosition
        """
        if not startPosition:
            startPosition = self.createPositionProportion(0.5, 0.5)
        position = copy.deepcopy(startPosition)
        MAX_MAG_DXI = 0.5  # target/maximum magnitude of xi increment
        XI_TOL = 1.0E-7
        old_dxi = None
        mag_old_dxi = 0
        mag_adxi = 0
        for it in range(100):
            xi1 = position.xi1
            xi2 = position.xi2
            x, d1, d2 = self.evaluateCoordinates(position, derivatives=True)
            deltax = [(targetx[c] - x[c]) for c in range(3)]
            # print('iter', it + 1, 'position', position, 'deltax', deltax, 'err', vector.magnitude(deltax))
            dxi1, dxi2 = calculate_surface_delta_xi(d1, d2, deltax)
            dxi = [dxi1, dxi2]
            mag_dxi = magnitude(dxi)
            # control oscillations
            if old_dxi and (dot(dxi, old_dxi) < -0.5 * (mag_old_dxi * mag_old_dxi)):
                factor = mag_dxi / (mag_dxi + mag_old_dxi)
                dxi1 *= factor
                dxi2 *= factor
                dxi = [dxi1, dxi2]
                mag_dxi *= factor
            position, onBoundary, adxi1, adxi2 = self._advancePosition(position, dxi1, dxi2, MAX_MAG_DXI=MAX_MAG_DXI)
            old_dxi = dxi
            mag_old_dxi = mag_dxi
            mag_adxi = magnitude([adxi1, adxi2])
            if mag_adxi < XI_TOL:
                # print("TrackSurface.findNearestPosition:  converged in", it + 1, "iterations, mag_dxi", mag_adxi)
                break
        else:
            print('TrackSurface.findNearestPosition:  Reach max iterations', it + 1, 'closeness in xi', mag_adxi)
        #print('final position', position)
        return position

    def findNearestPositionOnCurve(self, cx, cd1, loop=False, startCurveLocation=None, curveSamples: int=4):
        """
        Find nearest/intersection point on curve to this surface.
        :param cx: Coordinates along curve.
        :param cd1: Derivatives along curve.
        :param loop: True if curve loops back to first point, False if not.
        :param startCurveLocation: Optional initial location (element index, xi) to search from.
        If not supplied, uses element location at the nearest node coordinates.
        :param curveSamples: If startLocation not supplied, sets number of curve xi locations to evaluate when finding
        nearest initial curve location.
        :return: Nearest TrackSurfacePosition on self, nearest/intersection point on curve (element index, xi),
        isIntersection (True/False).
        """
        nCount = len(cx)
        assert nCount > 1
        eCount = nCount if loop else nCount - 1
        curveLocation = copy.copy(startCurveLocation) if startCurveLocation else None
        surfacePosition = None
        if curveLocation:
            targetx = evaluateCoordinatesOnCurve(cx, cd1, curveLocation, loop)
            surfacePosition = self.findNearestParameterPosition(targetx)
        else:
            nearestDistance = None
            sCount = eCount * curveSamples
            sLimit = sCount if loop else sCount + 1
            for s in range(sLimit):
                tmpCurveLocation = (s // curveSamples, (s % curveSamples) / curveSamples)
                if not loop and (s == sCount):
                    tmpCurveLocation = (tmpCurveLocation[0] - 1, 1.0)
                targetx = evaluateCoordinatesOnCurve(cx, cd1, tmpCurveLocation, loop)
                tmpSurfacePosition, tmpDistance = self.findNearestParameterPosition(targetx)
                if (nearestDistance is None) or (tmpDistance < nearestDistance):
                    nearestDistance = tmpDistance
                    curveLocation = tmpCurveLocation
                    surfacePosition = tmpSurfacePosition
        MAX_MAG_DXI = 0.5  # target/maximum magnitude of xi increment
        XI_TOL = 1.0E-7
        X_TOL = 1.0E-6 * max(self._xRange)
        lastOnBoundary = False
        last_dxi = None
        for it in range(100):
            x, d = evaluateCoordinatesOnCurve(cx, cd1, curveLocation, loop, derivative=True)
            surfacePosition = self.findNearestPosition(x, surfacePosition)
            onOtherBoundary = self._positionOnBoundary(surfacePosition)
            other_x = self.evaluateCoordinates(surfacePosition)
            r = sub(other_x, x)
            mag_r = magnitude(r)
            # print("    pos", curveLocation, onBoundary, "other", otherLocation, onOtherBoundary, "mag_r", mag_r)
            if mag_r < X_TOL:
                # print("TrackSurface.findNearestPositionOnCurve:  Found intersection: ", curveLocation, "on iter", it + 1)
                return surfacePosition, curveLocation, True
            n = normalize(cross(cross(d, r), d))
            r_dot_n = dot(r, n)
            if r_dot_n < 0:
                # flip normal to be towards other x
                n = [-s for s in n]
                r_dot_n = -r_dot_n
            r_out_of_plane = mult(n, r_dot_n)
            r_in_plane = sub(r, r_out_of_plane)
            # get tangential displacement u
            if onOtherBoundary:
                u = r_in_plane
            else:
                # add out-of-plane slope component
                factor = 1.0 + r_dot_n / mag_r
                u = mult(r_in_plane, factor)
            mag_dxi = dxi = magnitude(u) / magnitude(d)
            dxi = mag_dxi if (mag_dxi < MAX_MAG_DXI) else MAX_MAG_DXI
            if dot(u, d) < 0.0:
                dxi = -dxi
            # control oscillations
            if (it > 0) and ((dxi * last_dxi) < -0.5 * (last_dxi * last_dxi)):
                factor = mag_dxi / (mag_dxi + abs(last_dxi))
                dxi *= factor
                mag_dxi *= factor
            last_dxi = dxi
            bxi, faceNumber = incrementXiOnLine(curveLocation[1], dxi)
            curveLocation = (curveLocation[0], bxi)
            if faceNumber:
                curveLocation, onBoundary = updateCurveLocationTofaceNumber(curveLocation, faceNumber, eCount, loop)
                if onBoundary and lastOnBoundary:
                    # print("TrackSurface.findNearestPositionOnCurve:  Found nearest on boundary in", it + 1, "iterations")
                    break
                lastOnBoundary = onBoundary
            else:
                lastOnBoundary = False
            if mag_dxi < XI_TOL:
                # print("TrackSurface.findNearestPositionOnCurve:  Found nearest in", it + 1, "iterations, dxi", mag_dxi)
                break
        else:
            print('TrackSurface.findNearestPositionOnCurve did not converge:  Reached max iterations', it + 1,
                  'closeness in xi', mag_dxi)
        return surfacePosition, curveLocation, False

    def trackVector(self, startPosition, direction, trackDistance):
        """
        Track from startPosition the given distance in the vector direction.
        Approximate, uses improved Euler method (mean of original & final gradient).
        :param startPosition: TrackSurfacePosition
        :param direction: 3-D vector (x, y, z) to track along. Projected onto surface.
        :param trackDistance: Distance to track along. Can be negative.
        :return: Final TrackSurfacePosition
        """
        #print('TrackSurface.trackVector  start position', startPosition, 'direction', direction, 'distance', trackDistance)
        useDirection = direction
        useTrackDistance = trackDistance
        if trackDistance < 0.0:
            useDirection = [ -d for d in direction ]
            useTrackDistance = -trackDistance
        position = copy.deepcopy(startPosition)
        distance = 0.0
        distanceLimit = 0.9999*useTrackDistance
        MAX_MAG_DXI = 0.02  # target/maximum magnitude of xi increment

        while distance < useTrackDistance:
            xi1 = position.xi1
            xi2 = position.xi2
            ax, ad1, ad2 = self.evaluateCoordinates(position, derivatives = True)
            adelta_xi1, adelta_xi2 = calculate_surface_delta_xi(ad1, ad2, useDirection)
            #print('adelta_xi', adelta_xi1, adelta_xi2)
            scale = MAX_MAG_DXI/math.sqrt(adelta_xi1*adelta_xi1 + adelta_xi2*adelta_xi2)
            adxi1 = dxi1 = scale*adelta_xi1
            adxi2 = dxi2 = scale*adelta_xi2
            #print('adxi', adxi1, adxi2)
            for i in range(1):  # can try more in future
                # can go slightly outside element to get predictor/correct position
                position.xi1 = xi1 + dxi1
                position.xi2 = xi2 + dxi2
                bx, bd1, bd2 = self.evaluateCoordinates(position, derivatives = True)
                bdelta_xi1, bdelta_xi2 = calculate_surface_delta_xi(bd1, bd2, useDirection)
                # use mean of start and end derivatives
                delta_xi1 = 0.5*(adelta_xi1 + bdelta_xi1)
                delta_xi2 = 0.5*(adelta_xi2 + bdelta_xi2)
                scale = MAX_MAG_DXI/math.sqrt(delta_xi1*delta_xi1 + delta_xi2*delta_xi2)
                dxi1 = scale*delta_xi1
                dxi2 = scale*delta_xi2
            bxi1, bxi2, proportion, faceNumber = increment_xi_on_square(xi1, xi2, dxi1, dxi2)
            position.xi1 = bxi1
            position.xi2 = bxi2
            #print(distance, '-->', position)
            bx, bd1, bd2 = self.evaluateCoordinates(position, derivatives = True)
            bdelta_xi1, bdelta_xi2 = calculate_surface_delta_xi(bd1, bd2, useDirection)
            scale = MAX_MAG_DXI/math.sqrt(bdelta_xi1*bdelta_xi1 + bdelta_xi2*bdelta_xi2)
            bdxi1 = scale*bdelta_xi1
            bdxi2 = scale*bdelta_xi2
            #print('bdxi', bdxi1, bdxi2)
            ad = [ proportion*(adxi1*ad1[c] + adxi2*ad2[c]) for c in range(3) ]
            bd = [ proportion*(bdxi1*bd1[c] + bdxi2*bd2[c]) for c in range(3) ]
            # GRC check:
            #arcLength = computeCubicHermiteArcLength(ax, ad, bx, bd, rescaleDerivatives = True)
            arcLength = getCubicHermiteArcLength(ax, ad, bx, bd)
            #print('scales', vector.magnitude([ (bx[c] - ax[c]) for c in range(3) ]), vector.magnitude(ad), vector.magnitude(bd), 'arc length', arcLength)
            if (distance + arcLength) >= distanceLimit:
                # limit to useTrackDistance, approximately, and finish
                r = proportion*(useTrackDistance - distance)/arcLength
                position.xi1 = xi1 + r*dxi1
                position.xi2 = xi2 + r*dxi2
                #print(distance, '-->', position, '(final)')
                break
            if (arcLength == 0.0) and (not faceNumber):
                print('TrackSurface.trackVector. No increment at', position, 'final distance', distance, 'of', useTrackDistance)
                break
            distance += arcLength
            if faceNumber:
                onBoundary = self.updatePositionTofaceNumber(position, faceNumber)
                if onBoundary:
                    print('TrackSurface.trackVector:  End on boundary at', position)
                    break
                #print('  cross face', faceNumber, 'new position', position)
        return position

    def updatePositionTofaceNumber(self, position, faceNumber):
        """
        Update coordinates of TrackSurfacePosition position to cross
        the given face number, and either clamp to range if reached boundary,
        or loop around depending on mode.
        :return: 1 if on xi1 boundary, 2 if on xi2 boundary, 0 if not on a boundary.
        """
        onBoundary = 0
        if faceNumber == 1:  # xi1 == 0.0
            if position.e1 > 0:
                position.e1 -= 1
                position.xi1 = 1.0
            elif self._loop1:
                position.e1 = self._elementsCount1 - 1
                position.xi1 = 1.0
            else:
                position.xi1 = 0.0
                onBoundary = 1
        elif faceNumber == 2:  # xi1 == 1.0
            if position.e1 < (self._elementsCount1 - 1):
                position.e1 += 1
                position.xi1 = 0.0
            elif self._loop1:
                position.e1 = 0
                position.xi1 = 0.0
            else:
                position.xi1 = 1.0
                onBoundary = 1
        elif faceNumber == 3:  # xi2 == 0.0
            if position.e2 > 0:
                position.e2 -= 1
                position.xi2 = 1.0
            else:
                position.xi2 = 0.0
                onBoundary = 2
        elif faceNumber == 4:  # xi2 == 1.0
            if position.e2 < (self._elementsCount2 - 1):
                position.e2 += 1
                position.xi2 = 0.0
            else:
                position.xi2 = 1.0
                onBoundary = 2
        #if onBoundary:
        #    print('!!! Reached boundary of face', faceNumber, 'position', position)
        return onBoundary

    def generateMesh(self, region, startNodeIdentifier: int=None, startElementIdentifier: int=None, serendipity=False,
                     group_name=None):
        """
        Generate nodes and surface elements in region to show track surface.
        Client is required to define all faces.
        :param region: Zinc Region.
        :param startNodeIdentifier: Optional first node identifier to use.
        :param startElementIdentifier: Optional first 2D element identifier to use.
        :param serendipity: Set to True to use Hermite serendipity basis.
        :param group_name: Optional name of group to put new nodes and elements in.
        :return: next node identifier, next 2D element identifier
        """
        fieldmodule = region.getFieldmodule()
        with ChangeManager(fieldmodule):
            coordinates = find_or_create_field_coordinates(fieldmodule)
            group = find_or_create_field_group(fieldmodule, group_name) if group_name else None

            nodes = fieldmodule.findNodesetByFieldDomainType(Field.DOMAIN_TYPE_NODES)
            firstNodeIdentifier = startNodeIdentifier if startNodeIdentifier is not None else \
                max(get_maximum_node_identifier(nodes), 0) + 1
            nodeIdentifier = firstNodeIdentifier

            nodetemplate = nodes.createNodetemplate()
            nodetemplate.defineField(coordinates)
            nodetemplate.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_D_DS1, 1)
            nodetemplate.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_D_DS2, 1)
            if not serendipity:
                nodetemplate.setValueNumberOfVersions(coordinates, -1, Node.VALUE_LABEL_D2_DS1DS2, 1)

            mesh = fieldmodule.findMeshByDimension(2)
            firstElementIdentifier = startElementIdentifier if startElementIdentifier is not None else \
                max(get_maximum_element_identifier(mesh), 0) + 1
            elementIdentifier = firstElementIdentifier
            elementtemplate = mesh.createElementtemplate()
            elementtemplate.setElementShapeType(Element.SHAPE_TYPE_SQUARE)
            bicubicHermiteBasis = fieldmodule.createElementbasis(
                2, Elementbasis.FUNCTION_TYPE_CUBIC_HERMITE_SERENDIPITY if (serendipity and not self._nd12)
                   else Elementbasis.FUNCTION_TYPE_CUBIC_HERMITE)
            eft = mesh.createElementfieldtemplate(bicubicHermiteBasis)
            # keep cross derivatives so can experiment with effect
            # if not serendipity:
            #     # remove cross derivative terms for regular Hermite
            #     for n in range(4):
            #         eft.setFunctionNumberOfTerms(n * 4 + 4, 0)
            elementtemplate.defineField(coordinates, -1, eft)

            fieldcache = fieldmodule.createFieldcache()

            nodeset_group = group.getOrCreateNodesetGroup(nodes) if group else None
            for n1 in range(len(self._nx)):
                node = nodes.createNode(nodeIdentifier, nodetemplate)
                fieldcache.setNode(node)
                coordinates.setNodeParameters(fieldcache, -1, Node.VALUE_LABEL_VALUE, 1, self._nx[n1])
                coordinates.setNodeParameters(fieldcache, -1, Node.VALUE_LABEL_D_DS1, 1, self._nd1[n1])
                coordinates.setNodeParameters(fieldcache, -1, Node.VALUE_LABEL_D_DS2, 1, self._nd2[n1])
                if self._nd12:
                    coordinates.setNodeParameters(fieldcache, -1, Node.VALUE_LABEL_D2_DS1DS2, 1, self._nd12[n1])
                if nodeset_group:
                    nodeset_group.addNode(node)
                nodeIdentifier += 1
            del n1

            mesh_group = group.getOrCreateMeshGroup(mesh) if group else None
            nodesCount1 = self._elementsCount1 if self._loop1 else self._elementsCount1 + 1
            for e2 in range(self._elementsCount2):
                for e1 in range(self._elementsCount1):
                    nid0 = firstNodeIdentifier + e2 * nodesCount1
                    n1 = nid0 + e1
                    n2 = nid0 if (self._loop1 and ((e1 + 1) == self._elementsCount1)) else n1 + 1
                    n3 = n1 + nodesCount1
                    n4 = n2 + nodesCount1
                    nids = [n1, n2, n3, n4]
                    element = mesh.createElement(elementIdentifier, elementtemplate)
                    element.setNodesByIdentifier(eft, nids)
                    # print(elementIdentifier, element.isValid(), nids)
                    if mesh_group:
                        mesh_group.addElement(element)
                    elementIdentifier += 1

            fieldmodule.defineAllFaces()
            if group:
                # ensure all lines are in group
                group.setSubelementHandlingMode(FieldGroup.SUBELEMENT_HANDLING_MODE_FULL)
                mesh_group.addElementsConditional(group)

        return nodeIdentifier, elementIdentifier


def calculate_surface_delta_xi(d1, d2, direction):
    """
    Calculate dxi1, dxi2 in 3-D vector direction.
    :param d1, d2: Derivatives of coordinate w.r.t. xi1, xi2.
    :param direction: 3-D vector.
    :return: delta_xi1, delta_xi2
    """
    # overdetermined system (3-D vector, 2-D surface), solve least squares
    # A transpose A x = A transpose b
    a = [ [ 0.0, 0.0 ], [ 0.0, 0.0 ]]
    b = [ 0.0, 0.0 ]
    dx_dxi = [ d1, d2 ]
    for i in range(2):
        for j in range(2):
            for k in range(3):
                a[i][j] += dx_dxi[i][k]*dx_dxi[j][k]
        for k in range(3):
            b[i] += dx_dxi[i][k]*direction[k]
    # 2x2 matrix inverse
    deta = a[0][0]*a[1][1] - a[0][1]*a[1][0]
    if deta > 0.0:
        inva = [ [ a[1][1]/deta, -a[0][1]/deta ], [ -a[1][0]/deta, a[0][0]/deta ] ]
        delta_xi1 = inva[0][0]*b[0] + inva[0][1]*b[1]
        delta_xi2 = inva[1][0]*b[0] + inva[1][1]*b[1]
    else:
        # at pole: assume direction is inline with d1 or d2 and other is zero
        delta_xi2 = vector.dotproduct(d2, direction)
        if math.fabs(delta_xi2) > 0.0:
            delta_xi1 = 0.0
            delta_xi2 = (1.0 if (delta_xi2 > 0.0) else -1.0)*vector.magnitude(direction)/vector.magnitude(d2)
        else:
            delta_xi1 = vector.dotproduct(d1, direction)
            if math.fabs(delta_xi1) > 0.0:
                delta_xi1 = (1.0 if (delta_xi1 > 0.0) else -1.0)*vector.magnitude(direction)/vector.magnitude(d1)
                delta_xi2 = 0.0
    #delx = [ (delta_xi1*d1[c] + delta_xi2*d2[c]) for c in range(3) ]
    #print('delx', delx, 'dir', direction, 'diff', vector.magnitude([ (delx[c] - direction[c]) for c in range(3) ]))
    return delta_xi1, delta_xi2


def calculate_surface_axes(d1, d2, direction):
    """
    :return: Vectors ax1, ax2, ax3: ax1 in-plane in 3-D vector direction,
    ax2 in-plane normal to ax1 and ax3 normal to the surface plane.
    Vectors all have unit magnitude.
    """
    delta_xi1, delta_xi2 = calculate_surface_delta_xi(d1, d2, direction)
    ax1 = vector.normalise([ delta_xi1*d1[c] + delta_xi2*d2[c] for c in range(3) ])
    ax3 = vector.crossproduct3(d1, d2)
    mag3 = vector.magnitude(ax3)
    if mag3 > 0.0:
        ax3 = [ s/mag3 for s in ax3 ]
        ax2 = vector.normalise(vector.crossproduct3(ax3, ax1))
    else:
        ax3 = [ 0.0, 0.0, 0.0 ]
        ax2 = [ 0.0, 0.0, 0.0 ]
    return ax1, ax2, ax3


def increment_xi_on_square(xi1, xi2, dxi1, dxi2):
    """
    Increment xi1, xi2 by dxi1, dxi2 limited to square element bounds on [0,1].
    Works out face crossed first and limits that xi to 0.0 or 1.0 and other xi
    in proportion.
    :return: New xi1, xi2, proportion, face number 1-4 or None if within boundary.
    Proportion is 1.0 if increment is within element, otherwise equal to proportion
    of dxi1, dxi2 incremented to hit the boundary. If so limited to the boundary,
    the face number is returned as an integer:
    1 is xi1==0.0, 2 is xi1==1.0, 3 is xi2==0.0, 4 is xi2==1.0
    """
    onxi1 = nxi1 = xi1 + dxi1
    onxi2 = nxi2 = xi2 + dxi2
    proportion = 1.0
    faceNumber = None
    if (nxi1 < 0.0) or (nxi1 > 1.0) or (nxi2 < 0.0) or (nxi2 > 1.0):
        # come back in direction of dxi1, dxi2 to first boundary
        if (onxi1 < 0.0) and (dxi1 < 0.0):
            thisProportion = -xi1/dxi1
            if thisProportion < proportion:
                proportion = thisProportion
                faceNumber = 1
                nxi1 = 0.0
                nxi2 = xi2 + proportion*dxi2
        elif (onxi1 > 1.0) and (dxi1 > 0.0):
            thisProportion = (1.0 - xi1)/dxi1
            if thisProportion < proportion:
                proportion = thisProportion
                faceNumber = 2
                nxi1 = 1.0
                nxi2 = xi2 + proportion*dxi2
        if (onxi2 < 0.0) and (dxi2 < 0.0):
            thisProportion = -xi2/dxi2
            if thisProportion < proportion:
                proportion = thisProportion
                faceNumber = 3
                nxi1 = xi1 + proportion*dxi1
                nxi2 = 0.0
        elif (onxi2 > 1.0) and (dxi2 > 0.0):
            thisProportion = (1.0 - xi2)/dxi2
            if thisProportion < proportion:
                proportion = thisProportion
                faceNumber = 4
                nxi1 = xi1 + proportion*dxi1
                nxi2 = 1.0
        #print('  increment to face', faceNumber, 'xi (' + str(xi1) + ',' + str(xi2) + ')', 'nxi (' + str(nxi1) + ',' + str(nxi2) + ')')
    return nxi1, nxi2, proportion, faceNumber
