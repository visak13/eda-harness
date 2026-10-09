# The conversation

Every epic and story has one thread. People and seats post to it, and it is the record: nothing is
decided in a side chat.

## A question with options

When a seat needs a decision, it asks the owner on the thread. It sets out the options and recommends one.

![The architect asks Maya to choose between two merge strategies, and recommends one](../assets/guide/question-from-architect.png)

## An answer that quotes the question

Maya answers with **Reply**. Her answer links to the question and quotes the exact option she picked, with
a note. Anyone reading later sees what was asked and what was chosen.

![Maya's answer replies to the question and quotes the option she chose](../assets/guide/reply-with-quote.png)

## Quote anything

Select any passage in a message and a quote card opens. Add a note, and the quote goes into your next
message with a link back to where it came from.

![Selecting a passage in an engineer's message opens a quote card with a note](../assets/guide/quote-select.png)

A quote can come from another message, from a design document or from code. Here qa reports a failing
criterion and quotes all three: the engineer's claim, the design's rule and the line of code that breaks it.

![One finding quotes a message, the design and the code](../assets/guide/quotes-three-sources.png)

Each quote records its source exactly: the message and character range, the design version and lines, or
the file, lines and commit. A reader, human or seat, opens that passage and nothing more.

## Attachments

Attach images and videos to a message. Images show inline. Videos play in the thread.

Kenji, a guest teammate in Tokyo, attaches a phone screenshot of the conflict screen in Japanese:

![Kenji's message quotes the design line that fails and attaches a phone screenshot](../assets/guide/attachment-image.png)

An engineer answers a qa finding with a short screen recording of the fix:

![An engineer's answer with a screen recording that plays in the thread](../assets/guide/attachment-video.png)

## The composer

The composer at the bottom of the thread sets who the message goes to and what kind it is: a message, a
question, a steer that changes the plan, and so on. Type `@` to mention a person or a seat. The line
under the box says who will be notified.

![The composer with the @mention list showing people and seats](../assets/guide/composer-mention.png)

Type `$` to link a story, a document, a decision or a file. The list starts with this epic's own items. The
link opens the thing it names, so nobody has to paste an id.

![The composer with the $ list showing the epic's stories](../assets/guide/composer-refs.png)

## Find

**Find** (Ctrl+K) searches documents, messages and seats across the board.

![Find shows documents, messages and seats matching "tombstone"](../assets/guide/find.png)
