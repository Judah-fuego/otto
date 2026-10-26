# Otto — 3 minute demo

One person talks. One person drives. Lines in quotes are said out loud. Everything else is a click.

Do not launch the flight. A full coast is about five minutes and fires faults by itself. This pass stays staged and trips two alerts by hand.

## Before you walk up

1. `bash dev.sh`, then open http://localhost:3000.
2. Click **reset demo**.
3. Click **Ares** under Mars. When the launch card opens, press Escape. Leave the ship staged.
4. Turn the mic on if voice is up. If it is not, type the quoted lines. Same words either way.

If you are running long, skip the “why” question in minute two. The two alerts are the demo.

## 0:00 — What it is

Point at the chat.

> This is Otto, a copilot for a crewed ship. The crew only talks to Grok. Under the chat, two things are doing the work. A voyage calculator answers planning questions with real orbital math. SafeMode watches the telemetry and catches anomalies. The model explains. It does not decide. If a fix can be undone, SafeMode takes it. If it cannot, the crew has to approve it on screen.

## 0:30 — The ship

Point at **Ares** in the mission bar, then click the suggestion **Status report**.

> We are staged on Ares. Four people, Earth to Jezero Crater. I am asking for a status.

While the reply comes in, point at the map, the days to arrival, and the light delay.

> That answer came from a tool. Where the ship is, how long is left, how many days of oxygen, water, and food we still have after we arrive, and how long a call to Earth takes. Ground is a round trip at the speed of light, so a question to them is not a quick back and forth.

## 1:05 — Planning

Say, or type:

> What would this ship need to reach Pluto?

While it answers, point at the voyage card.

> It called the calculator. This is a direct Hohmann transfer, no gravity assist, so the number is honest: decades of coast, and a huge load of propellant. It should also say that real missions use flybys to cut that down. Grok is not doing the math itself.

## 1:35 — SafeMode acts

In the side panel, click **Reaction wheel** (labeled auto).

> SafeMode just caught the reaction wheel. Confidence is high, and switching to the backup wheel can be undone, so the gate marked it auto. It is already in the action log. Nobody clicked approve.

Say, or type:

> Why did SafeMode switch the reaction wheel?

> It should name the reading, the switch to the backup, and that the crew can undo it.

## 2:10 — The crew decides

Click **Cabin leak** (labeled crew). The decision card opens on its own.

> Different fault. Cabin pressure is falling. The fix is to seal the leaking module and vent it. That cannot be undone, so the gate stops and asks the crew. Saying yes in the chat does not count. The card is the only record.

Say, or type:

> Walk me through the life support procedure.

Point at the steps as they come back. Then hold the approve button until it commits.

> The crew holds to commit. Find the module, close the hatches, vent it. That is the product: catch the fault, say who acts, and leave the irreversible call with a person.

## 2:45 — Close

> Every alert ends one of three ways. Auto, when it is reversible and SafeMode is sure. Ask the crew, when it cannot be undone. Or send it to the ground, when we are not sure enough. SafeMode watches. Grok talks. The crew keeps the last word.

## If a judge asks

- **What about ground?** Click **Transponder**. Confidence is too low for an automatic fix, so the gate escalates. Earliest reply is twice the one-way light delay.
- **Is the model making the call?** The gate is in `app/gate.py`. Grok only explains the decision the code already made.
- **What is SafeMode?** An LSTM ensemble on NASA SMAP telemetry. The demo faults are scripted so the story is the same every time. The live monitor writes the same alert shape.
