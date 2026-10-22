---
name: unslop
description: Cut AI tells from any writing, German or English.
disable-model-invocation: true
---

# Unslop

Edit text to remove AI patterns. Scan for the patterns below, then rewrite. Preserve meaning and match the intended tone.

First detect the language of the text. Apply every rule in that language: use the DE examples for German text and the EN examples for English text. Never translate the text. Rules 34 to 37 apply only to German text.

## Patterns to detect and fix

Rule numbers are stable ids that other skills cite. A removed rule leaves a gap.

### Content

3. **Superficial -ing phrases.** EN: "highlighting...", "ensuring...", "reflecting...", "showcasing...", "fostering...". DE: angehängte Partizip- und "wodurch"-Konstruktionen wie "..., was die Bedeutung von X unterstreicht", "..., wodurch eine nahtlose Integration gewährleistet wird", "und trägt so zu ... bei". Delete or expand with real sources.
5. **Vague attributions.** EN: "Experts believe", "Industry reports suggest", "Some critics argue". DE: "Experten sind sich einig", "Studien zeigen", "Kritiker bemängeln", "Es heißt, dass". Name the source or delete.

### Language

7. **AI vocabulary.** Replace with plain words.
   - EN: Additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape (abstract), pivotal, showcase, tapestry (abstract), testament, underscore, vibrant.
   - DE: Darüber hinaus, zudem, des Weiteren, entscheidend, maßgeblich, zentral, essenziell, nahtlos, ganzheitlich, vielfältig, facettenreich, Facette, Landschaft (abstrakt), Zusammenspiel, eintauchen, beleuchten, unterstreichen, verdeutlichen, hervorheben, Mehrwert, spannend, robust, innovativ, zukunftsweisend, "in der heutigen schnelllebigen Welt", "nicht zuletzt", "Zeugnis ablegen".
8. **Fancy ways to say "is".** EN: "serves as", "stands as", "boasts", "features". DE: "fungiert als", "dient als", "stellt ... dar", "bildet", "zeichnet sich durch ... aus", "verfügt über", "bietet". Say "is"/"ist" or "has"/"hat".
9. **"Not just X, but Y."** DE: "nicht nur X, sondern auch Y", "Es geht nicht um X, es geht um Y". State the point directly instead.
10. **Rule of three.** Don't force ideas into groups of three ("schnell, sicher und zuverlässig"). Use the natural number.
11. **Synonym cycling.** EN: protagonist, main character, central figure, hero in one paragraph. DE: "das Tool", "die Lösung", "die Anwendung", "die Plattform" für dasselbe Ding. Pick one, repeat it.
12. **False ranges.** EN: "from X to Y", DE: "von X bis hin zu Y", where X and Y aren't on a meaningful scale. List topics directly.

### Style

13. **Dash overuse.** Avoid em dashes and German Gedankenstriche (– with spaces) entirely. Use periods or commas only (no parentheses, no en dashes, no hyphen-as-dash substitutes). If a thought needs separation, end the sentence or use a comma.
14. **Colon overuse.** Colons are fine before a list or example, not as mid-sentence connectors. "If you're coming from traditional automation: instead of registering event handlers, you describe conditions" adds nothing with the colon. DE: "Das Ergebnis: deutlich weniger Fehler." oder "Der Clou: ..." wird zu einem ganzen Satz. Rewrite to let the point stand on its own without comparison framing.
15. **Boldface overuse.** Don't bold every proper noun or acronym.
16. **Inline-header lists.** The tell is a bold label and colon that restates the line: "**Performance:** Performance improved..." / "**Sicherheit:** Die Sicherheit wurde verbessert...". Convert those to prose. A bold lead-in that ends in a period, names the item, and is followed by genuinely new detail ("**Schema in TypeScript.** Tables live in one file.") is fine, not a tell.
17. **Title case headings.** EN: use sentence case. DE: only the first word and nouns are capitalized. "Die Wichtigsten Vorteile Im Überblick" becomes "Die wichtigsten Vorteile im Überblick".
18. **Decorative emojis.** Remove from headings and bullets.
19. **Quotes.** EN: use straight quotes. DE: use straight quotes or German quotes („…"), consistently within the text. English curly quotes (“…”) in German text are a tell.

### Communication artifacts

20. **Chatbot phrases.** EN: "I hope this helps!", "Let me know if...", "Of course!", "Certainly!", "Found the smoking gun!". DE: "Ich hoffe, das hilft!", "Lass mich wissen, ob...", "Gerne!", "Selbstverständlich!", "Sehr gerne helfe ich dir dabei". Remove.
22. **Sycophantic tone.** EN: "Great question! You're absolutely right!" DE: "Tolle Frage!", "Da hast du völlig recht!", "Sehr guter Punkt!". Respond directly.

### Filler

23. **Filler phrases.** EN: "In order to" becomes "To". "Due to the fact that" becomes "Because". Delete "It is important to note that". DE: "aufgrund der Tatsache, dass" wird "weil". "im Rahmen von", "im Hinblick auf", "hinsichtlich", "bezüglich", "seitens" durch die direkte Präposition ersetzen. Streichen: "Es ist wichtig zu beachten, dass", "Es sei darauf hingewiesen, dass", "Grundsätzlich gilt", "An dieser Stelle sei erwähnt".
24. **Excessive hedging.** EN: "could potentially possibly be argued that it might" becomes "may". DE: "könnte unter Umständen möglicherweise eventuell" wird "kann". Modalpartikeln als Weichmacher ("eigentlich", "durchaus", "gewissermaßen", "im Grunde") streichen.
25. **Generic conclusions.** EN: "The future looks bright." DE: "Die Zukunft bleibt spannend.", "Es bleibt abzuwarten", "Fazit: X ist ein wichtiger Baustein". State specific plans or facts.

### Jargon

26. **Abstract metaphor nouns.** EN: substrate (base), wedge, wedge in (add), vector (way, method), locus, vantage, nexus, primitive as a noun, harness as a metaphor, surface as in "API surface", bedrock, scaffolding as a metaphor, modality, paradigm, gold-plating (more than the job needs), ratchet as a metaphor, evacuate for moving code (move out), endgame (the last phase), north star, flywheel. DE: Hebel, Stellschraube, Baustein, Fundament, Säule, Ökosystem, Leitplanken, Nordstern, Schwungrad, Paradigma, Klaviatur, Gamechanger. These read as technical but usually have a plainer concrete word. Pick the concrete word.

### Plain speech

27. **Say what it does, not how it feels.** "the database stays close at hand", "SQL you can read" name a feeling. The fix names the mechanism or a number: "`.toSQL()` returns the exact string sent to the database", "a column rename fails the build". DE: "Die Datenbank fühlt sich vertraut an" sagt nichts. "Ein umbenanntes Feld bricht den Build ab" sagt etwas. Ask what the sentence tells the reader to do or know, then write that. If you can't restate it as a concrete instruction, fact, or number, cut it. If the sentence could appear unchanged in another project's docs, it says nothing about this one. Cut it.
28. **Shorten or split dense sentences.** If the reader has to backtrack to parse a sentence, break it in two or drop clauses. One idea per sentence. DE: Schachtelsätze auflösen. Steht das Verb erst nach mehr als etwa zwölf Wörtern am Satzende, den Satz teilen.
29. **Active voice.** Prefer it. EN: catch "is/are/was/were + past participle" and name the actor: "queries are validated" becomes "the compiler validates queries". DE: "wird/wurde/werden + Partizip" und "erfolgt" erkennen und den Handelnden nennen: "Die Abfragen werden validiert" wird "Der Compiler validiert die Abfragen". Passive is fine only when the actor is unknown or genuinely doesn't matter.
30. **Cut adverbs, or use a stronger verb.** EN: "runs quickly" becomes "is fast" or the number, "significantly improves" becomes the measured delta. DE: "deutlich verbessert", "erheblich schneller", "besonders einfach" durch die Zahl oder ein stärkeres Verb ersetzen.
31. **Prefer the plain word.** EN: "utilize" and "leverage" become "use", "facilitate" becomes "help", "numerous" becomes "many", "in the event that" becomes "if". DE: "verwenden/nutzen" statt "einsetzen/zum Einsatz bringen/Gebrauch machen von", "viele" statt "zahlreiche/eine Vielzahl von", "falls/wenn" statt "für den Fall, dass", "ermöglichen" statt "in die Lage versetzen", "zeigen" statt "aufzeigen".
32. **Mannered prose.** Metaphor or flourish where a literal phrase exists: aphorisms ("wire it or delete it", "Weniger ist mehr"), rhetorical fragments for effect ("Und das Beste?"), personified code ("der Plan hält es fest"), figurative verbs ("rides along", "an Bord holen", "auf den Weg bringen"), stock framing phrases. Say what you mean. Rule 26 covers the metaphor nouns.
33. **Over-compression.** Dropped articles, verbless fragments, symbol-speak, and abbreviations that make the reader decode instead of read. "Parser rejects bad date → exit 2, no write" becomes "The parser rejects a bad date, exits with code 2, and writes nothing." DE: "Parser lehnt ungültiges Datum ab → Exit 2, kein Schreiben" wird "Der Parser lehnt ein ungültiges Datum ab, beendet sich mit Code 2 und schreibt nichts." Write whole sentences with their articles and verbs, and spell out arrows and abbreviations (auch "ggf.", "bzgl.", "i.d.R.", "z.T.").

### German only

34. **Nominalstil und Funktionsverbgefüge.** Substantivierungen auf -ung, -heit, -keit mit leerem Verb zurück ins Verb verwandeln. "Die Durchführung der Prüfung erfolgt durch das Team" wird "Das Team prüft". "zur Anwendung kommen" wird "angewendet werden", "eine Entscheidung treffen" wird "entscheiden", "in Betracht ziehen" wird "erwägen", "Berücksichtigung finden" wird "berücksichtigt werden".
35. **Lehnübersetzungen aus dem Englischen.** "Sinn machen" wird "Sinn ergeben" oder "sinnvoll sein". "einen Unterschied machen" wird "etwas ändern/bewirken". "am Ende des Tages" wird "letztlich" oder streichen. "in 2025" wird "2025" oder "im Jahr 2025". "Das ist, wo ..." wird "Hier ...". "Ich freue mich darauf zu sehen, wie ..." wird "Ich bin gespannt, wie ...".
36. **Unnötige Anglizismen.** Englische Wörter ersetzen, wenn ein gebräuchliches deutsches Wort existiert und der Text sonst deutsch ist: "Challenge" wird "Herausforderung" oder "Problem", "Insights" wird "Erkenntnisse", "Learnings" wird "Erfahrungen", "committen" (im Sinne von zusagen) wird "zusagen". Etablierte Fachbegriffe (Deployment, Branch, Commit, Pull Request) bleiben.
37. **Anrede.** Du oder Sie, nicht gemischt. Die Anrede des Ausgangstextes beibehalten. Kein unpersönliches "man", wenn der Leser gemeint ist.
