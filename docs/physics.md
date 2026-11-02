# The physics and maths behind the planner

This document derives every formula the planner uses. The code comments give
the short form and point to the sections here.

Throughout, one made-up **example space** keeps the numbers concrete: a 20 m²
insulated storage building with a 1 kW heater. The tests use the same space.

| Quantity | Symbol | Example |
|---|---|---|
| Heat loss | $UA$ | 25 W/°C |
| Heat capacity | $C$ | 0.56 kWh/°C |
| Heater power | $P$ | 1 kW |
| Cooling rate | $k = UA / C$ | 0.0446 /h |
| Maximum rise | $G = P / UA$ | 40 °C |
| Half-life of warmth | $\ln 2 / k$ | 15.5 h |

All temperatures are in °C, energies in kWh, prices in cents per kWh
including VAT.

---

## Humidity

Air can hold at most a certain amount of water vapour, which grows steeply
with temperature. The **saturation vapour pressure** is well approximated by
the Magnus formula (coefficients over water, Sonntag 1990, good from −45 to
+60 °C):

$$
e_s(T) = 6.112\ \text{hPa} \cdot \exp\left(\frac{a\,T}{b + T}\right),
\qquad a = 17.62,\quad b = 243.12\ ^\circ\text{C}
$$

**Relative humidity** compares the vapour present, $e$, with that maximum:

$$
RH = 100 \cdot \frac{e}{e_s(T)}
$$

The **dew point** $T_d$ is the temperature at which the same vapour would
saturate the air, $e_s(T_d) = e$. Solving the Magnus formula for it:

$$
\gamma = \ln\frac{RH}{100} + \frac{a\,T}{b + T}, \qquad
T_d = \frac{b\,\gamma}{a - \gamma}
$$

The dew point measures how much water the air holds, whatever its
temperature. Warming the air leaves $T_d$ unchanged but raises $e_s(T)$, so the
relative humidity falls:

$$
RH(T) = 100 \cdot \exp\left(\frac{a\,T_d}{b + T_d} - \frac{a\,T}{b + T}\right)
$$

That is why heating dries a space without removing any water: the same water
is a smaller share of what the warmer air could hold. Mould and rust respond to
relative humidity at the surfaces, so a lower relative humidity is what
matters.

### Sliding humidity limit

Mould growth and corrosion slow down a lot in the cold, so the allowed
relative humidity rises as the space gets colder. Below a warm reference
temperature $T_w$ the target climbs by a slope $s$ per degree, up to a cap:

$$
RH_\text{target}(T) = \min\Big(\max\big(RH_w + s\,(T_w - T),\ RH_w\big),\ RH_\text{max}\Big)
$$

$$
RH_\text{critical}(T) = RH_\text{target}(T) + \Delta_\text{critical}
$$

With the defaults ($RH_w$ = 65 %, $T_w$ = 15 °C, $s$ = 1 %/°C,
$RH_\text{max}$ = 80 %, $\Delta_\text{critical}$ = 10 %):

| Space at | Target | Critical |
|---|---|---|
| 15 °C or warmer | 65 % | 75 % |
| 10 °C | 70 % | 80 % |
| 0 °C | 80 % (capped) | 90 % |

**How warm is warm enough?** For the water the indoor air holds now (its dew
point), the planner needs the lowest temperature at which $RH(T)$ is within
the limit. Both $RH(T)$ and the sliding limit fall as $T$ rises, so there is no
closed form; the crossing is found by bisection between $T_d$ and $T_d + 40$
°C, to well under 0.001 °C.

---

## Warming and cooling

Heat leaks out of the space in proportion to how much warmer it is than
outside (Newton's law of cooling), and the heaters add their power:

$$
C\,\frac{dT}{dt} = -UA\,(T - T_\text{out}) + P\,u, \qquad u \in \{0, 1\}
$$

- $UA$: heat loss through walls, roof, floor and air leaks, kW/°C
- $C$: heat stored per degree in the air, the structure and the contents,
  kWh/°C
- $P$: the heaters' power while on

Dividing by $UA$ gives two numbers with an intuitive meaning:

$$
k = \frac{UA}{C} \quad \text{(cooling rate, 1/h)}, \qquad
G = \frac{P}{UA} \quad \text{(maximum rise, °C)}
$$

$$
\frac{dT}{dt} = -k\,\big(T - (T_\text{out} + G\,u)\big)
$$

For a constant outdoor temperature the solution settles exponentially
towards an equilibrium:

$$
T(t) = T_\text{eq} + \big(T(0) - T_\text{eq}\big)\,e^{-k t}, \qquad
T_\text{eq} = \begin{cases} T_\text{out} + G & \text{heating} \\ T_\text{out} & \text{coasting} \end{cases}
$$

$G$ is how far above outside the heaters could hold the space if they ran
for ever; $1/k$ is the time constant. **Half the warmth above outside is
lost in** $\ln 2 / k$ hours.

The planner heats in one block from the start of an hour, so an hour with
$m$ minutes of heating is two pieces: settle towards $T_\text{out} + G$ for
$m/60$ hours, then towards $T_\text{out}$ for the rest.

**The example space.** Coasting from 15 °C at 5 °C outside for 5 hours:

$$
T = 5 + (15 - 5)\,e^{-0.0446 \cdot 5} = 5 + 10 \cdot 0.80 = 13\ ^\circ\text{C}
$$

A full hour of heating from 5 °C at −5 °C outside:

$$
T = (-5 + 40) + (5 - 35)\,e^{-0.0446} \approx 6.3\ ^\circ\text{C}
$$

**Why the room and the heaters are kept apart.** $UA$ and $C$ describe the
building; $P$ is whatever heats it. Adding a second heater doubles $G$ but
leaves $k$ alone, and nothing has to be relearned.

### Coasting time

How long the space can go unheated before cooling to a lower limit
$T_\text{low}$ follows from the same solution. With a constant outdoor
temperature:

$$
t = \frac{1}{k}\,\ln\frac{T - T_\text{out}}{T_\text{low} - T_\text{out}}
$$

The planner steps through the hourly outdoor forecast instead, and
interpolates within the hour where the limit is crossed.

---

## Learning

The room ($UA$ and $C$) is learned from the space's own history, logged in
15-minute steps. Over one step of length $\Delta t$, with the outdoor
temperature roughly constant, the model above becomes linear:

$$
\Delta T_\text{end} = a\,\Delta T_\text{start} + c\,E, \qquad \Delta T = T_\text{in} - T_\text{out}
$$

$$
a = e^{-k\,\Delta t}, \qquad c = \frac{1 - a}{UA\,\Delta t}
$$

where $E$ is the energy the heaters used in the step. An electric heater turns
all its electricity into heat, so measured energy is exactly the heat
delivered: a cold-start surge simply counts as more heat. Without an energy
meter, $E$ is estimated as the share of the step the heaters were on times
their power.

$a$ and $c$ follow from ordinary least squares, via the 2×2 normal
equations:

$$
\begin{pmatrix} \sum x^2 & \sum x E \\ \sum x E & \sum E^2 \end{pmatrix}
\begin{pmatrix} a \\ c \end{pmatrix}
= \begin{pmatrix} \sum x y \\ \sum E y \end{pmatrix},
\qquad x = \Delta T_\text{start},\ y = \Delta T_\text{end}
$$

and the room from them:

$$
UA = \frac{1 - a}{c\,\Delta t}, \qquad C = \frac{UA\,\Delta t}{-\ln a}
$$

The heaters' power $P$ is the measured energy divided by the hours on.

**How sure is it?** The scatter of the fit gives the covariance of $(a, c)$:

$$
\mathrm{Cov}(a, c) = \sigma^2\,(X^\top X)^{-1}, \qquad
\sigma^2 = \frac{\text{SSE}}{n - 2}
$$

and the delta method carries it to $UA$ and $C$. For any $f(a, c)$:

$$
\mathrm{Var}(f) \approx \left(\frac{\partial f}{\partial a}\right)^2 \mathrm{Var}(a)
+ \left(\frac{\partial f}{\partial c}\right)^2 \mathrm{Var}(c)
+ 2\,\frac{\partial f}{\partial a}\frac{\partial f}{\partial c}\mathrm{Cov}(a, c)
$$

The learned room is used once both $UA$ and $C$ are known to within 25 %
(their standard error relative to their value). Until then the space runs as
a plain thermostat.

**Learning fast.** Heating and coasting steps are both needed: heating
steps show how much a kWh warms the room, coasting steps how fast it loses
heat. A **calibration run** right after setup provides both: an hour of
heating, then 2.5 hours of coasting, in the cheapest hour ahead. In the cold,
one run is usually enough. Heating itself creates the temperature difference
the fit needs, so even mild weather gets there within a few runs.

### Anomalies

A door left open, a warm car parked inside or sun on the wall make some steps
miss the model badly. Before the final fit, such steps are dropped:

1. Fit, and compute each step's miss (residual) $r_i$.
2. Estimate the spread robustly, from the median absolute deviation:
   $\hat\sigma = 1.4826 \cdot \mathrm{median}\,|r_i - \mathrm{median}(r)|$.
   For normally distributed misses this equals the standard deviation, but a
   few huge misses barely move it, unlike a plain RMS, which they would
   inflate enough to slip through.
3. Drop every step missing by more than $3\hat\sigma$ (and never by less than
   0.05 °C), **and the 30 minutes after it**: once a door closes, the air
   warms back up from the walls and floor faster than the model expects.
4. Repeat until nothing changes, at most 5 rounds.

---

## The planner

### Lower limits

Each hour of the known price list gets a lower limit: the lowest temperature
the space should have at the end of that hour. It is the highest of these
wishes:

| Wish | Kind | Lower limit |
|---|---|---|
| Minimum | hard | minimum temperature + margin |
| Critical humidity | hard | warm enough that RH stays below critical |
| Override | hard | the override target, while it runs |
| Humidity | soft | warm enough that RH stays at the target |
| Dew point | soft | outside dew point + margin |

**Soft wishes wait** in hours whose spot price is above the price ceiling.

### The optimisation

For each hour $h$ the planner picks $m_h \in \{0, 15, 30, 45, 60\}$ minutes of
heating, as one block from the start of the hour, minimising

$$
\sum_h \Big[\, (p_h + f)\,P\,\frac{m_h}{60}
+ \lambda_\text{hard}\,\max(0,\ L^\text{hard}_h - T_h)
+ \lambda_\text{soft}\,\max(0,\ L^\text{soft}_h - T_h) \,\Big]
$$

- $p_h$: the hour's spot price; $f$: the fixed costs per kWh
- $T_h$: the temperature at the end of the hour, from the model above
- $L_h$: the hour's lower limits; $\lambda$: penalties per °C·h below them
  (1000 c hard, 5 c soft)

Wishes are penalties rather than walls, so there is always a plan: when a
hard limit can't be reached the plan does its best and says so.

The fixed costs belong in the objective: they make every kWh cost something
even at night, so the planner pre-heats only when the price difference is
worth the heat that leaks away meanwhile.

**Solving it.** Dynamic programming over a 0.1 °C temperature grid. Going
backwards from the last known hour, for every hour $h$ and every grid
temperature $T$ at its start, the cheapest way to finish the window is

$$
V_h(T) = \min_{m}\Big[\text{cost}_h(m, T) + V_{h+1}\big(T_\text{end}(T, m)\big)\Big],
\qquad V_{H}(\cdot) = 0
$$

and following the cheapest choices forwards from the current temperature
gives the plan. A 48-hour window takes a fraction of a second.

**Recalculated every hour.** The plan is rebuilt each hour from the real
temperature, prices and forecast (model predictive control), so model errors
don't accumulate: a wrong guess costs at most an hour.

**Before the room is learned** the same wishes drive a plain thermostat with
a 1 °C band instead.

---

## Comparison

### Comparison thermostat

What would a plain thermostat holding a constant temperature $T_\text{set}$
have cost? A constant temperature stores no heat, so the thermostat only
replaces what leaks out, capped at the heaters' power:

$$
E_h = \min\Big(P_h,\ UA_h\,\max\big(0,\ T_\text{set} - T_{\text{out},h}\big)\Big) \cdot 1\ \text{h}
$$

$$
\text{cost}_h = E_h \cdot \pi_h
$$

where $\pi_h$ is the energy price (spot plus fixed costs) **in force in that
hour**. Every input is taken as it was in that hour: the room learned at the
time ($UA_h$, $P_h$, from the space's own heat loss and heater power
sensors), the outdoor temperature and the price. A later change, to the
building or to the tariff, shows from then on instead of rewriting the past.

The series for different temperatures aren't multiples of one another: the
$\max(0, \cdot)$ leaves mild hours out of the cooler thermostats only, and the
cap $P_h$ bites on the warmer ones first.

**The real curve** to set them against, the *metered cost*, prices the
heaters' measured energy the same way:

$$
\text{metered cost}_h = E^\text{metered}_h \cdot \pi_h
$$

### Day-ahead forecast

Comparing an hour with the plan in force when it started would show nothing:
the heaters follow that plan exactly. When tomorrow's prices arrive (early
afternoon), tomorrow's plan is kept as it is, 10 to 34 hours ahead: its
planned energy, cost and indoor temperature for every hour. The gaps between
that forecast and what actually happened show where the weather forecast, the
learned room or real life differed from what was expected.
