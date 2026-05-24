# Compatibility wrapper for inherited Nix references.
#
# New package definitions should import ./superforecasting-agent.nix.  Keep this
# path available while downstream flakes migrate away from the Hermes filename.
args:
import ./superforecasting-agent.nix args
