# Energy-consistent numerical scheme

This development note is separate from `scale_continuation.html`.

The Fourier vorticity equation is split into

$$
\partial_t\widehat\omega=-D(k)\widehat\omega+\widehat N(\omega),
\qquad D(k)=\nu k^8+\alpha.
$$

The quadratic term uses a two-thirds-dealiased, skew-symmetric average of its
advective and conservative forms. The linear damping is advanced with an
integrating-factor RK4 step, so the stiff hyperviscous term is treated by its
exact exponential rather than explicit extrapolation.

Forcing is a separate stochastic kick in the fixed forcing shell. A random
real-valued field is Fourier transformed, projected onto the shell, and made
orthogonal to the current forced-shell state in the kinetic-energy inner
product. It is then normalized so that

$$
E(\widehat\omega+\delta\widehat\omega)-E(\widehat\omega)
=\varepsilon\,\Delta t
$$

to floating-point precision. This removes the singular feedback coefficient
used by negative-damping forcing when the forced shell becomes depleted.

Results are accepted only if inviscid energy and enstrophy drift, the forced
energy-balance residual, timestep refinement, and resolution refinement pass
the thresholds encoded in `energy_consistent_solver.py`.
