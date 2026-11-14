# Independent BGIN verifier

`bgin_core/` started as the byte-for-byte snapshot of the Octane workspace
`tools/bgin_core` used by Binary GIN Editor 0.5.0. Editor 0.6.0 extends this
snapshot with independent 3.7.0/5.8.0 readers and writers, explicit wire profiles,
property variants and hashed color channels. It is no longer byte-identical to
the older workspace copy. Do not overwrite these additions during an upstream
sync. Tests compare forced rebuilding and edits with the editor's separate
JSON codec on real input corpora.

The editor compiles these modules into its worker to independently verify
BGIN before writing it. The snapshot is distributed under the repository terms.
