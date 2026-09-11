"""Disposable update probe: native TLS failures must not kill a forecast session."""
import json


def main():
    from superforecasting_agent.runtime import banner
    behind = banner.check_for_updates()
    print(json.dumps({'behind': behind, 'latest_version': banner._latest_version}))


if __name__ == '__main__':
    main()
