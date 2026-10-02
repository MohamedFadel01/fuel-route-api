# How a trip is planned

Austin to Denver is the example. You ask for latitude 30.2672, longitude -97.7431, and the finish is latitude 39.7392, longitude -104.9903. The truck holds 500 miles of fuel, burns 1 gallon every 10 miles, and leaves with a full tank that costs nothing.

## 1. One road, from the router

The server asks OSRM once. The router moves each end onto a road:

| Place | You asked for | The road point | How far it moved |
|---|---|---|---|
| Start | 30.2672, -97.7431 | 30.267208, -97.743130 | 0.0019 miles |
| Finish | 39.7392, -104.9903 | 39.738466, -104.990291 | 0.0506 miles |

Both moves are under the 5-mile limit, so the trip continues. The answer is a line of 10,708 points. OSRM says that line is 916.841 miles and takes 59,782.9 seconds.

## 2. The length used for fuel

Fuel ignores OSRM’s 916.841. It adds the distance between each pair of points on that line. One real pair, about 90 miles out of Austin:

- 31.263477, -98.440076
- 31.273969, -98.449452

Those two points are 0.912209 miles apart. The formula is the great-circle distance, with the Earth radius at 3,958.7613 miles:

\[
h = \sin^2(\Delta lat/2) + \cos(lat_1)\cos(lat_2)\sin^2(\Delta lon/2)
\]

\[
miles = 2 \times 3958.7613 \times \arcsin(\sqrt{h})
\]

For this pair, \(h = 0.000000013274\) and the result is 0.912209 miles. Adding every pair gives **917.323 miles**. That is the length the fuel math uses.

The line is then replaced by a point every 0.499903 miles, 1,836 points in all. Mile 100 of the drive is latitude 31.386983, longitude -98.542816.

## 3. Stations near that line

Every station that has coordinates is compared with those 1,836 points. A station counts when its nearest route point is within 10 miles. This road has **103** such stations. Each one is given the mile marker of that nearest point. A station 3 miles off the highway is still treated as sitting on the highway at that mile. The extra 3 miles are not added to the trip.

## 4. Where it buys

The drive is a line from mile 0 to mile 917.323. The finish counts as a pump with price 0, because arriving is better than buying more fuel.

Standing anywhere, the rule is:

- If a strictly cheaper pump is within 500 miles, buy only enough to reach the nearest one. If the tank already reaches it, buy nothing.
- If nothing cheaper is within 500 miles, fill the tank, then drive to the cheapest pump you can reach. If several share that price, drive to the farthest.

The tank starts full, so the cheap pumps around Austin are skipped. It rolls forward through them without buying:

| Mile | Station | Price | What happens |
|---|---|---|---|
| 0.000 | Mustang Xpress, Austin (30.267150, -97.743060) | $3.332 | Tank still full. A cheaper pump is ahead. Buy 0. |
| 7.998 | Circle K, Austin (30.355991, -97.685224) | $2.932 | Still reaches a cheaper pump. Buy 0. |
| 10.998 | Quiktrip, Pflugerville (30.421765, -97.585415) | $2.882 | Buy 0. |
| 23.995 | PWI, Georgetown (30.632690, -97.677230) | $2.799 | Buy 0. |
| 67.487 | Circle K, Lampasas (31.055740, -98.179578) | $2.759 | Next cheaper place is Denver, 850 miles away. |

At Lampasas the tank has \(500 - 67.487 = 432.513\) miles left. Nothing cheaper is inside one tank, and $2.759 is the best price it can still reach. It buys the 67.487 miles it has already burned, which fills the tank back to 500. It then drives to the farthest pump at that same price: Roscoe, at mile 258.450.

**Roscoe Travel Plaza**, 32.445950, -100.538720, still $2.759. It arrives with \(500 - 190.963 = 309.037\) miles. Denver is still 658.873 miles away, so it fills again: buy 190.963 miles. The cheapest pump inside the next 500 miles is Plainview, which costs a little more.

**CEFCO, Plainview**, 34.186786, -101.749045, $2.83233333, mile 417.419. It arrives with 341.031 miles. Denver is \(917.323 - 417.419 = 499.904\) miles ahead, which fits in one tank, and the finish is the cheapest “pump” there is. So it buys only the missing fuel:

\[
499.904 - 341.031 = 158.873 \text{ miles}
\]

It reaches Denver with an empty tank.

## 5. Gallons and money

Gallons are miles divided by 10, then rounded to the nearest thousandth. A cost is gallons times the station’s price, rounded to the nearest cent. Halves round up.

| Stop | Miles of fuel | Gallons | Price | Cost |
|---|---:|---:|---:|---:|
| Lampasas | 67.487 | 6.749 | 2.759 | 6.749 × 2.759 = **$18.62** |
| Roscoe | 190.963 | 19.096 | 2.759 | 19.096 × 2.759 = **$52.69** |
| Plainview | 158.873 | 15.887 | 2.83233333 | 15.887 × 2.83233333 = **$45.00** |

The trip burns \(917.323 / 10 = 91.732\) gallons. It buys \(6.749 + 19.096 + 15.887 = 41.732\) gallons. The other 50.000 gallons are the free starting tank. The bill is \(18.62 + 52.69 + 45.00 = \) **$116.31**.
