r"""
==========================================
Drive Hamiltonian (:mod:`qudit_sim.drive`)
==========================================

.. currentmodule:: qudit_sim.drive

See :ref:`drive-hamiltonian` for theoretical background.
"""

from typing import Callable, Optional, Union, Tuple, List, Any
import copy
from dataclasses import dataclass
import warnings
import numpy as np

from .expression import (ParameterExpression, Parameter, TimeFunction, ConstantFunction, PiecewiseFunction,
                         TimeType, ArrayType, ReturnType)
from .pulse import Pulse
from .config import config

HamiltonianCoefficient = Union[str, ArrayType, TimeFunction]

class DriveTerm:
    r"""Data class representing a drive.

    Args:
        frequency: Carrier frequency of the drive. None is allowed if amplitude is a PulseSequence
            that starts with SetFrequency.
        amplitude: Function :math:`r(t)`.
        constant_phase: The phase value of `amplitude` when it is a str or a callable and is known to have
            a constant phase. None otherwise.
        sequence: Drive sequence. If this argument is present and not None, all other arguments are ignored,
            except when the sequence does not start with SetFrequency and frequency is not None.
    """
    def __init__(
        self,
        frequency: Optional[Union[float, Parameter]] = None,
        amplitude: Union[float, complex, str, np.ndarray, Parameter, Callable] = 1.+0.j,
        constant_phase: Optional[Union[float, Parameter]] = None,
        sequence: Optional[List[Any]] = None
    ):
        if sequence is None:
            if frequency is None or amplitude is None:
                raise RuntimeError('Frequency and amplitude must be set if not using a PulseSequence.')

            self._sequence = [SetFrequency(frequency), amplitude]
            self.constant_phase = constant_phase
        else:
            self._sequence = list(sequence)
            if frequency is not None and not isinstance(self._sequence[0], SetFrequency):
                self._sequence.insert(0, SetFrequency(frequency))

            self.constant_phase = None

    @property
    def frequency(self) -> Union[float, Parameter, None]:
        frequencies = set(inst.value for inst in self._sequence if isinstance(inst, SetFrequency))
        if len(frequencies) == 1:
            return frequencies.pop()
        else:
            # Unique frequency cannot be defined
            return None

    @property
    def amplitude(self) -> Union[float, complex, str, np.ndarray, Parameter, Callable, None]:
        if len(self._sequence) == 2:
            return self._sequence[1]
        else:
            # Unique amplitude cannot be defined
            return None

    def generate_fn(
        self,
        frame_frequency: float,
        drive_base: complex,
        rwa: bool
    ) -> Tuple[HamiltonianCoefficient, HamiltonianCoefficient]:
        r"""Generate the coefficients for X and Y drives.

        Args:
            frame_frequency: Frame frequency :math:`\xi_k^{l}`.
            drive_base: Factor :math:`\alpha_{jk} e^{i \rho_{jk}} \frac{\Omega_j}{2}`.
            rwa: If True, returns the RWA coefficients.

        Returns:
            X and Y coefficient functions.
        """
        funclist = list()

        frequency = None
        phase_offset = 0.
        time = 0.

        if rwa:
            generate_single = _generate_single_rwa
        else:
            generate_single = _generate_single_full

        for inst in self._sequence:
            if isinstance(inst, ShiftFrequency):
                if frequency is None:
                    raise RuntimeError('ShiftFrequency called before SetFrequency')

                frequency += inst.value
            elif isinstance(inst, ShiftPhase):
                phase_offset += inst.value
            elif isinstance(inst, SetFrequency):
                frequency = inst.value
            elif isinstance(inst, SetPhase):
                if frequency is None:
                    raise RuntimeError('SetPhase called before SetFrequency')

                phase_offset = inst.value - frequency * time
            elif isinstance(inst, Delay):
                funclist.append((time, ConstantFunction(0.), ConstantFunction(0.)))
                time += inst.value
            else:
                if frequency is None:
                    raise RuntimeError('Pulse called before SetFrequency')

                if isinstance(inst, str):
                    # If this is actually a static expression, convert to complex
                    try:
                        inst = complex(eval(inst))
                    except:
                        pass

                fn_x, fn_y = generate_single(inst, frequency, frame_frequency,
                                             drive_base * np.exp(-1.j * phase_offset), time,
                                             self.constant_phase)
                funclist.append((time, fn_x, fn_y))

                if isinstance(inst, Pulse):
                    time += inst.duration
                else:
                    # Indefinite drive
                    time = np.inf
                    break

        funclist.append((time, None, None))

        if len(funclist) == 1:
            raise ValueError('No drive amplitude specified')

        elif len(funclist) == 2:
            fn_x = funclist[0][1]
            fn_y = funclist[0][2]

        elif all(isinstance(func, TimeFunction) for _, func, _ in funclist[:-1]):
            timelist = list(f[0] for f in funclist)
            xlist = list(f[1] for f in funclist[:-1])
            ylist = list(f[2] for f in funclist[:-1])

            fn_x = PiecewiseFunction(timelist, xlist)
            fn_y = PiecewiseFunction(timelist, ylist)

        elif all(isinstance(func, np.ndarray) for _, func, _ in funclist[:-1]):
            fn_x = np.concatenate(list(x for _, x, _ in funclist[:-1]))
            fn_y = np.concatenate(list(y for _, _, y in funclist[:-1]))

        else:
            print(str(funclist[0][1]), str(funclist[1][1]))
            raise ValueError('Cannot generate a Hamiltonian coefficient from amplitude types'
                             f' {list(type(func) for _, func, _ in funclist[:-1])}')

        return fn_x, fn_y


def _generate_single_rwa(amplitude, frequency, frame_frequency, drive_base, tzero, constant_phase=None):
    detuning = frequency - frame_frequency

    if isinstance(frequency, Parameter):
        is_resonant = False
    else:
        is_resonant = np.isclose(detuning, 0.)

    if isinstance(amplitude, (float, complex, Parameter)):
        # static envelope
        envelope = amplitude * drive_base

        if is_resonant:
            if isinstance(envelope, Parameter):
                envelope = ConstantFunction(envelope)

            return envelope.real, envelope.imag

        elif (isinstance(amplitude, Parameter) or isinstance(frequency, Parameter)
              or config.pulse_sim_solver == 'jax'):
            fun = ExpFunction(-detuning) * envelope
            return fun.real, fun.imag

        else:
            fn_x = []
            fn_y = []
            if envelope.real != 0.:
                fn_x.append(f'({envelope.real} * cos({detuning} * t))')
                fn_y.append(f'({-envelope.real} * sin({detuning} * t))')
            if envelope.imag != 0.:
                fn_x.append(f'({envelope.imag} * sin({detuning} * t))')
                fn_y.append(f'({envelope.imag} * cos({detuning} * t))')

            return ' + '.join(fn_x), ' + '.join(fn_y)

    elif isinstance(amplitude, str):
        if tzero != 0. and 't' in amplitude:
            warnings.warn('Possibly time-dependent string amplitude in a sequence detected; this is not supported.',
                          UserWarning)

        envelope = f'({drive_base}) * ({amplitude})'

        if is_resonant:
            return f'({envelope}).real', f'({envelope}).imag'

        elif constant_phase is None:
            return (f'({envelope}).real * cos({detuning} * t) + ({envelope}).imag * sin({detuning} * t)',
                    f'({envelope}).imag * cos({detuning} * t) - ({envelope}).real * sin({detuning} * t)')

        else:
            phase = np.angle(drive_base) + constant_phase
            return (f'abs({envelope}) * cos({phase} - ({detuning} * t))',
                    f'abs({envelope}) * sin({phase} - ({detuning} * t))')

    elif isinstance(amplitude, np.ndarray):
        envelope = amplitude * drive_base

        if is_resonant:
            return envelope.real, envelope.imag

        else:
            fun = ExpFunction(-detuning) * envelope
            return fun.real, fun.imag

    elif callable(amplitude):
        if not isinstance(amplitude, TimeFunction):
            amplitude = TimeFunction(amplitude)

        envelope = amplitude * drive_base
        envelope.tzero = tzero

        if is_resonant:
            return envelope.real, envelope.imag

        elif constant_phase is None:
            fun = envelope * ExpFunction(-detuning)
            return fun.real, fun.imag

        else:
            phase = constant_phase + np.angle(drive_base)
            absf = abs(envelope)
            return absf * CosFunction(-detuning, phase), absf * SinFunction(-detuning, phase)

    else:
        raise TypeError(f'Unsupported amplitude type f{type(amplitude)}')


def _generate_single_full(amplitude, frequency, frame_frequency, drive_base, tzero, constant_phase=None):
    if isinstance(amplitude, (float, complex, Parameter)):
        # static envelope
        double_envelope = amplitude * 2. * drive_base

        if (isinstance(amplitude, Parameter) or isinstance(frequency, Parameter)
            or config.pulse_sim_solver == 'jax'):
            labframe_fn = (double_envelope.real * CosFunction(frequency)
                           + double_envelope.imag * SinFunction(frequency))
        else:
            labframe_fn_terms = []
            if double_envelope.real != 0.:
                labframe_fn_terms.append(f'({double_envelope.real} * cos({frequency} * t))')
            if double_envelope.imag != 0.:
                labframe_fn_terms.append(f'({double_envelope.imag} * sin({frequency} * t))')

            labframe_fn = ' + '.join(labframe_fn_terms)
            if len(labframe_fn_terms) > 1:
                labframe_fn = f'({labframe_fn})'

    elif isinstance(amplitude, str):
        if tzero != 0. and 't' in amplitude:
            warnings.warn('Possibly time-dependent string amplitude in a sequence detected; this is not supported.',
                          UserWarning)

        double_envelope = f'({2. * drive_base}) * ({amplitude})'

        if constant_phase is None:
            labframe_fn = f'({double_envelope} * (cos({frequency} * t) - 1.j * sin({frequency} * t))).real'

        else:
            phase = constant_phase + np.angle(drive_base)
            if isinstance(constant_phase, Parameter):
                labframe_fn = CosFunction(-frequency, phase) * abs(double_envelope)
            else:
                labframe_fn = f'abs({double_envelope}) * cos({phase} - ({frequency} * t))'

    elif isinstance(amplitude, np.ndarray):
        double_envelope = amplitude * 2. * drive_base

        labframe_fn = (ExpFunction(-frequency) * double_envelope).real

    elif callable(amplitude):
        if not isinstance(amplitude, TimeFunction):
            amplitude = TimeFunction(amplitude)

        double_envelope = amplitude * 2. * drive_base

        if tzero != 0.:
            double_envelope = copy.copy(double_envelope)
            double_envelope.tzero = tzero

        if constant_phase is None:
            labframe_fn = (double_envelope * ExpFunction(-frequency)).real

        else:
            phase = constant_phase + np.angle(drive_phase)
            absf = abs(double_envelope)
            labframe_fn = absf * CosFunction(-frequency, phase)

    else:
        raise TypeError(f'Unsupported amplitude type f{type(amplitude)}')

    if isinstance(labframe_fn, str):
        if frame_frequency == 0.:
            return labframe_fn, ''
        else:
            return (f'{labframe_fn} * cos({frame_frequency} * t)',
                    f'{labframe_fn} * sin({frame_frequency} * t)')

    else:
        if frame_frequency == 0.:
            return labframe_fn, ConstantFunction(0.)
        else:
            return labframe_fn * CosFunction(frame_frequency), labframe_fn * SinFunction(frame_frequency)


class OscillationFunction(TimeFunction):
    def __init__(
        self,
        op: Callable,
        frequency: Union[float, ParameterExpression],
        phase: Union[float, ParameterExpression] = 0.
    ):
        self.op = op
        self.frequency = frequency
        self.phase = phase

        if isinstance(frequency, ParameterExpression):
            if isinstance(phase, ParameterExpression):
                fn = self._fn_PE_PE
                parameters = frequency.parameters + phase.parameters
            else:
                fn = self._fn_PE_float
                parameters = frequency.parameters
        else:
            if isinstance(phase, ParameterExpression):
                fn = self._fn_float_PE
                parameters = phase.parameters
            else:
                fn = self._fn_float_float
                parameters = ()

        super().__init__(fn, parameters)

    def _fn_PE_PE(self, t: TimeType, args: Tuple[Any, ...] = ()) -> ReturnType:
        freq_n_params = len(self.frequency.parameters)
        return self.op(self.frequency.evaluate(args[:freq_n_params]) * t
                       + self.phase.evaluate(args[freq_n_params:]))

    def _fn_PE_float(self, t: TimeType, args: Tuple[Any, ...] = ()) -> ReturnType:
        return self.op(self.frequency.evaluate(args) * t + self.phase)

    def _fn_float_PE(self, t: TimeType, args: Tuple[Any, ...] = ()) -> ReturnType:
        return self.op(self.frequency * t + self.phase.evaluate(args))

    def _fn_float_float(self, t: TimeType, args: Tuple[Any, ...] = ()) -> ReturnType:
        return self.op(self.frequency * t + self.phase)


class CosFunction(OscillationFunction):
    def __init__(
        self,
        frequency: Union[float, ParameterExpression],
        phase: Union[float, ParameterExpression] = 0.
    ):
        super().__init__(config.npmod.cos, frequency, phase)

class SinFunction(OscillationFunction):
    def __init__(
        self,
        frequency: Union[float, ParameterExpression],
        phase: Union[float, ParameterExpression] = 0.
    ):
        super().__init__(config.npmod.sin, frequency, phase)

class ExpFunction(OscillationFunction):
    @staticmethod
    def _op(x):
        return config.npmod.cos(x) + 1.j * config.npmod.sin(x)

    def __init__(
        self,
        frequency: Union[float, ParameterExpression],
        phase: Union[float, ParameterExpression] = 0.
    ):
        super().__init__(ExpFunction._op, frequency, phase)

@dataclass(frozen=True)
class ShiftFrequency:
    """Frequency shift in rad/s."""
    value: Union[float, Parameter]

@dataclass(frozen=True)
class ShiftPhase:
    """Phase shift (virtual Z)."""
    value: float

@dataclass(frozen=True)
class SetFrequency:
    """Frequency setting in rad/s."""
    value: Union[float, Parameter]

@dataclass(frozen=True)
class SetPhase:
    """Phase setting."""
    value: float

@dataclass(frozen=True)
class Delay:
    """Delay in seconds."""
    value: float
