# Avalon DOT Traffic Signal Timing Policy Manual

Jurisdiction: State of Avalon (tier: STATE)

Notice: SYNTHETIC DEMONSTRATION DOCUMENT. This jurisdiction and its provisions are fictional and exist only to exercise the multi jurisdictional reasoning of this software. It is not the law of any real state or municipality.

## Clause 3.1 Applicability and Relationship to the MUTCD

Standard:
01
This manual adopts the Manual on Uniform Traffic Control Devices, 11th Edition, as the standard for traffic control devices on all public roads in the State of Avalon. Where this manual is more restrictive than the MUTCD, this manual governs. No provision of this manual relaxes a MUTCD Standard.

Support:
02
Local agencies may adopt requirements that are more restrictive than this manual by ordinance. The most restrictive applicable requirement governs a signalized location.

## Clause 3.2 Yellow Change Interval

Standard:
01
The yellow change interval shall be computed with the ITE kinematic equation Y = t + v / (2a + 2Gg) using a perception reaction time t of 1.0 seconds, a deceleration rate a of 10.0 feet per second squared, the approach grade G as a decimal (negative for downgrade), and a clearance speed v equal to the posted speed limit of the approach. For protected left turn movements the clearance speed shall be 10 mph below the through clearance speed but not less than 20 mph.

Standard:
02
The yellow change interval shall not be less than 3.0 seconds and shall be rounded up to the nearest 0.1 second supported by the controller unit.

Guidance:
03
Yellow change intervals longer than 6 seconds should be avoided; where the kinematic value exceeds 6 seconds, advance warning and dilemma zone detection should be considered.

## Clause 3.3 Red Clearance Interval

Standard:
01
The red clearance interval shall be computed with the ITE kinematic red clearance equation, R = (W + L) / v, using the width from the stop line to the far side of the last conflicting lane, a design vehicle length of 20 feet and the clearance speed defined in Clause 3.2, and shall not be less than 1.0 seconds.

## Clause 3.4 Consistency of Clearance Intervals

Standard:
01
The displayed yellow change interval shall equal the programmed value in every cycle of a timing plan. The red clearance interval shall not be shortened or omitted on a cycle by cycle basis except as permitted by MUTCD Section 4F.17.

Standard:
02
Any deviation between displayed and programmed clearance intervals recorded in the controller high resolution event log shall be treated as an equipment malfunction and reported to the signal maintenance supervisor within 24 hours.

## Clause 3.5 Controller Assemblies and Malfunction Management

Standard:
01
Controller assemblies shall conform to NEMA TS 2 or the ATC standards. Minimum yellow change interval monitoring in the malfunction management unit shall be enabled on every vehicle channel.

Guidance:
02
Malfunction management unit logs should be downloaded after every reported crash at a signalized location and preserved with the controller event log.

## Clause 3.6 Vehicle Detection

Standard:
01
Detector failures reported by controller diagnostics, including open loop, shorted loop, excessive inductance change and watchdog failure, shall place the affected phase on maximum recall until repaired.

Guidance:
02
Advance detection providing dilemma zone protection should be restored as soon as practical, because maximum recall removes green extension for vehicles approaching at speed.
