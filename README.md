# Spot Heating Planner

A Home Assistant integration that keeps an unheated or lightly heated space
(a garage, storage building, cottage or crawl space) **frost-free and dry at the
lowest electricity cost.** The minimum temperature is yours to set, below
freezing too, for a space that only needs to stay dry.

It learns how the space warms and cools, then plans the heating hour by hour on
spot prices and the weather forecast: it pre-heats in cheap hours so the space
can coast through expensive ones, and heats for humidity only when it's worth
it.

> **Work in progress.** Not yet released; expect changes.

## How it works, in short

1. **Learns the room.** From 15-minute steps of indoor and outdoor temperature
   and the heaters' energy, it fits the room's heat loss and heat capacity. A
   calibration run right after setup (an hour of heating, then coasting) gets
   it there within hours, and it keeps refining afterwards. Until then it runs
   as a plain thermostat.
2. **Plans every hour.** Each hour has a lower limit: the highest of the
   minimum temperature, critical humidity, a manual override, the humidity target and
   the outdoor dew point. The planner finds the cheapest heating that keeps
   every hour above its limit, over all the prices known (up to the end of
   tomorrow).
3. **Safety first.** A lost indoor sensor heats, dropping below the emergency
   temperature heats at any price, and nothing heats above the maximum, whatever the plan says.

The physics and maths are explained in [docs/physics.md](docs/physics.md).

## Requirements

- Home Assistant 2026.10 or newer
- One or more heaters on switchable entities (smart plugs, switches)
- An indoor temperature sensor

Optional, and better with them:

- indoor and outdoor humidity, outdoor temperature (learning needs the outdoor
  temperature)
- the heaters' energy meters (kWh), for accurate learning and costs
- a weather entity with an hourly forecast
- spot prices: the official **Nord Pool** integration, or any entity with a
  price list in this integration's format

## Installation

Through HACS as a custom repository:

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/jussimi/ha-spot-heating-planner`,
   type: **Integration**
3. Install **Spot Heating Planner** and restart Home Assistant
4. Settings → Devices & services → **Add integration** → Spot Heating Planner

## Setup

The setup asks three things:

1. **The space:** a name, the heaters, and the sensors.
2. **Where prices come from:** Nord Pool, an entity with a price list, or none
   (minimum temperature and moisture only).
3. **The source's details:** for Nord Pool the integration entry, area,
   currency and VAT; for an entity the format and any VAT to add.

Each space is its own entry; add one per garage, cottage or cellar. To change a
space's heaters, sensors or price source later, use **Reconfigure** on the
integration card. What it has learned is kept.

## Entities

Each space is one device with these entities.

**Sensors**

| Entity | Meaning |
|---|---|
| Mode | Why the space is or isn't heating: keeping the minimum, humidity, preheating, waiting for a cheaper hour, … Its attributes hold the plan hour by hour. |
| Next heating | Start of the next planned heating |
| Planned heating / cost, next 24 h | What the plan will do |
| Spot price | This hour's price as the planner sees it (c/kWh incl. VAT), with the known hours in its `forecast` attribute |
| Energy price | Spot price plus the fixed costs: what a kWh costs now |
| Heating energy / cost | Running totals, measured or estimated |
| Can coast for | Hours the space can go unheated before reaching its minimum |
| Room model, heat loss, heat capacity, half-life, heater power … | The learned room (diagnostic) |

**Binary sensors:** heating, can't keep up, indoor sensor stuck.

**Switch:** *Control heaters*. Off: the space keeps planning and shows why, but
leaves the heaters alone.

**Buttons:** start override, cancel override, calibrate.

**Numbers (settings):** minimum and maximum temperature, emergency temperature, override
temperature and length, humidity target (warm and cold), dew point margin,
price ceiling, fixed energy cost (transfer fee, electricity tax and margin per
kWh), heater power (used without an energy meter).

**Options** (Configure on the integration card): the comparison thermostats'
temperatures.

## Statistics series

Besides its sensors, each space writes hourly series into Home Assistant's
long-term statistics, which the **Statistics graph** card can show by hour,
day, week or month:

| Series | Meaning |
|---|---|
| `…_day_ahead_energy`, `…_day_ahead_cost`, `…_day_ahead_temperature` | Tomorrow's plan as it looked the day before, recorded as each hour ends |
| `…_thermostat_5_cost`, `…_thermostat_5_energy`, … | What a plain thermostat at that temperature would have used and cost, for the same room |
| `…_metered_cost` | The heaters' measured energy, priced: the real curve |

Each comparison hour uses that hour's own inputs: the room learned at the time,
the outdoor temperature and the energy price then in force. The series are
written up to date at start and every night, one year of history at a time.

In the card's entity picker the series are named after the space, for example
*Garage thermostat 5 °C cost*.

## Comparing with a thermostat

For any period and any temperatures, the `spot_heating_planner.compare_thermostat`
action returns what plain thermostats would have cost next to the actual cost:

```yaml
action: spot_heating_planner.compare_thermostat
data:
  config_entry_id: <the space>
  temperatures: [4, 5, 8, 10]
  start: "2026-11-01"
  end: "2026-11-30"
response_variable: comparison
```

The response lists, for each temperature, the energy, cost and savings, next to
the actual energy and cost and the average indoor temperature actually kept.
Only hours with every reading count, so every figure covers the same hours.
Run it from Developer tools → Actions, or from a script.

## Dashboard examples

Replace `garage` with your space's name, and `<entry>` with its id (the
Statistics graph card's picker finds the series by name).

**Cost by day: actual vs. plain thermostats** (built-in card)

```yaml
type: statistics-graph
title: Heating cost by day
chart_type: bar
period: day
stat_types: [change]
entities:
  - entity: sensor.garage_heating_cost
    name: Actual
  - entity: spot_heating_planner:<entry>_thermostat_5_cost
    name: Thermostat 5 °C
  - entity: spot_heating_planner:<entry>_thermostat_10_cost
    name: Thermostat 10 °C
```

**Forecast vs. actual, by hour** (built-in card)

```yaml
type: statistics-graph
title: Day-ahead forecast vs. actual
chart_type: bar
period: hour
days_to_show: 2
stat_types: [change]
entities:
  - entity: sensor.garage_heating_energy
    name: Actual
  - entity: spot_heating_planner:<entry>_day_ahead_energy
    name: Forecast the day before
```

**Predicted vs. actual indoor temperature** (built-in card)

```yaml
type: statistics-graph
title: Indoor temperature, forecast vs. actual
chart_type: line
period: hour
days_to_show: 3
stat_types: [mean]
entities:
  - entity: sensor.garage_indoor_temperature
    name: Actual
  - entity: spot_heating_planner:<entry>_day_ahead_temperature
    name: Forecast the day before
```

**The plan ahead** (needs [ApexCharts card](https://github.com/RomRider/apexcharts-card))

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Heating plan
graph_span: 36h
span:
  start: hour
now:
  show: true
  label: Now
yaxis:
  - id: price
    min: 0
    decimals: 0
  - id: minutes
    opposite: true
    min: 0
    max: 60
    show: false
  - id: temperature
    opposite: true
    decimals: 1
series:
  - entity: sensor.garage_mode
    name: Spot price (c/kWh)
    type: column
    yaxis_id: price
    data_generator: |
      return entity.attributes.plan.map(h => [new Date(h.start).getTime(), h.price]);
  - entity: sensor.garage_mode
    name: Heating (min)
    type: column
    yaxis_id: minutes
    data_generator: |
      return entity.attributes.plan.map(h => [new Date(h.start).getTime(), h.minutes]);
  - entity: sensor.garage_mode
    name: Predicted temperature
    type: line
    yaxis_id: temperature
    data_generator: |
      return entity.attributes.plan.map(h => [new Date(h.start).getTime() + 3600000, h.temperature]);
```

## Safety

The planner is software running on a computer; frost damage is real damage.
Keep a second line of defence:

- **The heaters' own thermostats**, set to the highest temperature you'd ever
  want, stop them if control is lost while on.
- **Smart plugs that power on after an outage**, so a power cut doesn't leave
  the heaters off.

## Development

```bash
uv sync                    # Python and the dev tools
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # strict type check
uv run pre-commit install  # run the checks before every commit
```

The planner's logic lives in `custom_components/spot_heating_planner/core/`:
plain Python with no Home Assistant imports, tested on its own. A throwaway
Home Assistant with a fake space for trying things in a browser:
`docker compose -f dev/compose.yaml up`, then <http://localhost:8123>.

## License

MIT
