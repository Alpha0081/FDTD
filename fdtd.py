#!/usr/bin/env python
# -*- coding: utf-8 -*-

from dataclasses import dataclass, fields
from typing import Sequence

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg

from boundary import (ABCBase, Boundary, PECLeft, PECRight)
from constants import W_0, c
from display import Display
from exceptions import (AreaSizeError, BoundaryTypeError, ScValueError,
                        SpaceStepError, TimeDurationError, TimeStepError)
from layer import Layer
from probe import Probe
from progress_bar import ConsoleOutput, ProgressBar
from source import Source

@dataclass
class Boundaries:
    left: Boundary
    right: Boundary


class FDTD:
    def __init__(
        self, area_size: float, space_step: float, time_duration: float, Sc: float
    ) -> None:
        self.__validate_init_data(area_size, space_step, time_duration, Sc)

        self.__dx: float = space_step
        self.__area_size: int = int(area_size // self.__dx)
        self.__Sc: float = Sc
        self.__time_duration: float = time_duration
        self.__dt: float = self.__dx * self.__Sc / c
        self.__time_counts: int = int(self.__time_duration // self.__dt)
        self.__E: npt.NDArray[np.float64] = np.zeros(self.__area_size)
        self.__H: npt.NDArray[np.float64] = np.zeros(self.__area_size - 1)
        self.__eps: npt.NDArray[np.float64] = np.ones(self.__area_size)
        self.__sigma: npt.NDArray[np.float64] = np.zeros(self.__area_size)
        self.__mu: npt.NDArray[np.float64] = np.ones(self.__area_size - 1)
        self.__borders: list[float] = []
        self.__boundary: Boundaries = Boundaries(
            left=PECLeft(), right=PECRight())
        self.__display: Display = Display(
            (0, self.__area_size), (-1.1, 1.1), "Ez В/м")
        self.__display.activate(self.__dx)
        self.__sources: list[Source] = []
        self.__probes: list[Probe] = []
        self.__layers: list[Layer] = []

    def __validate_init_data(self, area_size: float, space_step: float, time_duration: float, Sc: float) -> bool:
        self.__validate_area(area_size, space_step)
        self.__validate_Sc(Sc)
        self.__validate_time(space_step, time_duration, Sc)
        return True

    def __validate_area(self, area_size: float, space_step: float) -> bool:
        if area_size <= 0:
            raise AreaSizeError
        if space_step > area_size:
            raise SpaceStepError
        return True

    def __validate_time(self, space_step: float, time_duration: float, Sc: float) -> bool:
        if time_duration <= 0:
            raise TimeDurationError
        dt = space_step * Sc / c
        if dt > time_duration:
            raise TimeStepError
        return True

    def __validate_Sc(self, Sc: float):
        if Sc <= 0:
            raise ScValueError

    def update_boundary(self) -> bool:
        left, right = self.__boundary.left, self.__boundary.right
        if isinstance(left, ABCBase):
            left.eps = self.__eps[0]
            left.mu = self.__mu[0]
            left.Sc = self.__Sc
            left.update_coefficient()
        if isinstance(right, ABCBase):
            right.eps = self.__eps[-1]
            right.mu = self.__mu[-1]
            right.Sc = self.__Sc
            right.update_coefficient()
        if not isinstance(left, Boundary) or not isinstance(right, Boundary):
            raise BoundaryTypeError
        return True

    def analyze(self) -> bool:
        self.update_boundary()
        self.__display.draw_probes(self.__probes, self.__dx)
        self.__display.draw_borders(self.__borders)
        self.__display.draw_sources(self.__sources, self.__dx)

        self.__ceze = (1 - self.__sigma) / (1 + self.__sigma)
        self.__cezh = W_0 / (self.__eps * (1 + self.__sigma))
        self.__progress = ProgressBar(ConsoleOutput())
        self.__current_time = 0
        self.timer = pg.Qt.QtCore.QTimer()
        self.timer.timeout.connect(self.next_iteration)
        self.timer.start(int(1000 // 144))
        pg.exec()
        return True

    def show_probe_signals(self):
        self.__display.show_probe_signals(
            self.__time_duration, self.__dt, self.__dx, self.__probes)

    def next_iteration(self):
        if int(self.__current_time // self.__dt) < self.__time_counts:
            self.__H = self.__H + (self.__E[1:] - self.__E[:-1]) * self.__Sc / (
                W_0 * self.__mu
            )
            for source in self.__sources:
                self.__H[source.position - 1] -= (
                    self.__Sc / (W_0 * self.__mu[source.position - 1]) *
                    source.E(0, self.__current_time / self.__dt)
                )

            self.__E[1:-1] = (
                self.__ceze[1:-1] * self.__E[1:-1]
                + (self.__H[1:] - self.__H[:-1]) *
                self.__Sc * self.__cezh[1:-1]
            )

            for field in fields(self.__boundary):
                boundary = getattr(self.__boundary, field.name)
                boundary.update_field(self.__E, self.__H)

            for source in self.__sources:
                self.__E[source.position] += (
                    self.__Sc
                    / (self.__eps[source.position] * self.__mu[source.position]) ** .5
                    * source.E(-.5, (self.__current_time / self.__dt + .5))
                )

            for probe in self.__probes:
                probe.add_data(self.__E, self.__H)

            self.__progress.show(self.__current_time /
                                 self.__dt, self.__time_counts - 1)
            self.__display.draw(self.__E, self.__current_time)
            self.__current_time += self.__dt
        else:
            self.timer.stop()
        return True

    def add_probes(self, probes_position: float | Sequence[float]) -> bool:
        match probes_position:
            case float():
                self.__probes.append(
                    Probe(int(probes_position // self.__dx), self.__time_counts)
                )
            case[*args]:
                for probe_position in args:
                    self.__probes.append(
                        Probe(int(probe_position // self.__dx),
                              self.__time_counts)
                    )

            case _:
                raise TypeError
        return True

    def add_source(self, source: Source) -> bool:
        source.position = int(source.position // self.__dx)
        source.eps = self.__eps[source.position]
        source.mu = self.__mu[source.position]
        source.Sc = self.__Sc
        source.dt = self.__dt
        self.__sources.append(source)
        return True

    def add_layer(self, layer: Layer) -> bool:
        layer.name = "Layer" + str(len(self.__layers))
        self.__layers.append(layer)
        begin, end = int(
            layer.area[0] / self.__dx), int(layer.area[1] / self.__dx)
        self.__eps[begin:end] = layer.eps
        self.__mu[begin:end] = layer.mu
        self.__sigma[begin:end] = layer.sigma
        self.__borders.append(layer.area[0])
        self.__borders.append(layer.area[1])
        return True

    def delete_layer(self, name: str) -> bool:
        for i, layer in enumerate(self.__layers):
            if layer.name == name:
                begin, end = int(layer.area[0] / self.__dx), int(
                    layer.area[1] / self.__dx
                )
                self.__eps[begin:end] = 1
                self.__mu[begin:end] = 1
                self.__sigma[begin:end] = 0
                self.__borders.pop(2 * i + 1)
                self.__borders.pop(2 * i)
                self.__layers.pop(i)
                break
        return True

    def set_left_boundary(self, boundary: Boundary) -> bool:
        self.__boundary.left = boundary
        return True

    def set_right_boundary(self, boundary: Boundary) -> bool:
        self.__boundary.right = boundary
        return True

    @property
    def Sc(self) -> float:
        return self.__Sc

    @property
    def dt(self) -> float:
        return self.__dt

    @property
    def dx(self) -> float:
        return self.__dx

    @property
    def mu(self) -> np.ndarray:
        return self.__mu

    @property
    def eps(self) -> np.ndarray:
        return self.__eps
