"""Disposable update probe: native TLS failures must not kill a forecast session."""
import json


def main():
    import platform
    import ssl
    import sys
    # Emitted before native certificate loading so a fatal signal retains the
    # exact runtime identity alongside faulthandler stacks in the parent log.
    print(json.dumps({"python": sys.version, "platform": platform.platform(),
                      "openssl": ssl.OPENSSL_VERSION}), file=sys.stderr, flush=True)
    from superforecasting_agent.runtime import banner
    behind = banner.check_for_updates()
    print(json.dumps({'behind': behind, 'latest_version': banner._latest_version}))


if __name__ == '__main__':
    main()
