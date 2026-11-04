# UCR Chatbot 2.0

## What this project is

A bot on a LINE Official Account (UCR / TONKIT Lab). It invites people in a community
to talk about the environment and infrastructure near their home. Each chat becomes
**reports** with a location. The end result is **pins on a map for the city design
team**, who use them to choose what to improve first.

A sensor measures 38°C at a spot. A grandmother who walks to the market every morning
says she can no longer make it, because there is no shade. **We collect her story.**
The bot does not send help and does not fix problems.

**The AI writes the questions.** This whole project came from dropping fixed questions
and the state machine. If you are about to write a ready-made message or a yes/no
button card in the code, you are going backwards: a sensor can already give checkbox
answers. **We want the story people tell.** This includes broadcast messages, when the
bot messages people first: the AI writes them fresh every time.

Fixed text is allowed in only 3 cases (TC7 in `docs/requirements/02-constraints.md`:
the AI always writes the messages people get):
1. The fallback text when the AI is down or the quota is used up, so the reporter is never left in silence.
2. Messages an admin types.
3. The PDPA Flex message with its accept button, and the welcome text after accept. The words must stay fixed because they are reviewed.
