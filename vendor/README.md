# Independent BGIN verifier

`bgin_core/` contains the runtime modules of the Octane workspace codec from
`tools/bgin_core`, copied byte for byte for Binary GIN Editor 0.5.0. The
workspace codec remains the upstream owner. Update the snapshot from one
upstream revision and run the byte-exact conversion checks after syncing.

The editor compiles these modules into its worker to independently verify
BGIN before writing it. The snapshot is distributed under the repository terms.
