# Giving human instructions

An operator following instructions for an external system — GitHub, a cloud console, a billing
dashboard — is trusting the steps as given; verifying each one against the vendor's own docs
was the point of asking in the first place, and defeats the point if the operator has to do it
anyway. [`human-instructions`](../../plugins/tautline-core/skills/human-instructions/SKILL.md)
is the live skill that verifies before writing such a step; this page is the reasoning under
it.

## A specific authoritative page outlasts a homepage

A link to a vendor's documentation home page is still correct a year later and useless the
entire time — the reader repeats the search the instructions' author should already have done.
A link to the exact page the steps were verified against fails loudly the day that page moves,
which is the failure that actually gets noticed and fixed, instead of the one that quietly
wastes the reader's time forever.

## The steps that apply depend on prerequisites the operator has not stated

Role, plan tier, account age, and organization versus personal ownership each send a vendor's
UI down a different path for what is nominally the same setting. Instructions that do not name
which prerequisite they assume are instructions that work for whichever operator happens to
match the unstated assumption, and silently mislead everyone who does not.

## An unverified UI path labeled as unverified is still useful; invented and confident is not

A menu path recalled from training data or an old screenshot is right more often than not, and
wrong in exactly the way that strands an operator mid-flow with no path back to a correct
answer. Naming the path as unverified, next to the source that would verify it, costs one
sentence and leaves the operator able to tell "confirmed against the current UI" apart from
"best recollection" before they are already three clicks into acting on it.

## The operator's screen outranks an API or CLI result about that screen

When what the operator reports seeing contradicts what a query says should be there, the query
is the more likely place to be wrong — stale cache, wrong scope, wrong account, a field whose
name no longer means what it used to. Debugging the query against the observed screen finds the
actual mismatch; restating the query's answer over what the operator is looking at does not,
and asks them to doubt the one piece of evidence in the exchange that is live.
