"""Sign in to Copilot through the Copilot SDK itself (device code), with nothing else installed.

Run with the Python of the venv that has `microsoft-copilot-sdk`:
    python login.py                    # github.com account
    python login.py --kind entra       # account managed through Microsoft Entra (EMU)
    python login.py --kind proxima     # GitHub Enterprise Cloud on a *.ghe.com host (asks for the host)
It prints a one-time code and a URL: open the URL in a browser, type the code, approve.
The runtime keeps the sign-in (Windows Credential Manager), so the probe and later runs use it.
It never prints a token.
"""
import argparse
import asyncio
import tempfile

from copilot import CopilotClient
from copilot._generated.rpc import AuthLoginAdvanceRequest, AuthLoginBeginRequest, AuthLoginCancelRequest, AuthLoginMethod, LoginProviderKind


def value(x):
    return getattr(x, "value", x)


async def main(args):
    client = CopilotClient(mode="coding-agent")
    await client.start()
    auth = await client.get_auth_status()
    print("before: signed in = %s" % auth.is_authenticated)
    if auth.is_authenticated and not args.again:
        print("Already signed in (%s). Use --again to sign in anyway." % auth.auth_type)
        await client.stop()
        return
    with tempfile.TemporaryDirectory() as folder:
        session = await client.create_session(working_directory=folder)
        login = session.rpc.accounts.login
        kind = {"github": LoginProviderKind.GITHUB_DOT_COM, "entra": LoginProviderKind.ENTRA, "proxima": LoginProviderKind.PROXIMA}[args.kind]
        method = AuthLoginMethod.DEVICE_CODE if args.kind != "entra" else None
        begun = await login.begin(AuthLoginBeginRequest(kind=kind, method=method))
        flow, step = begun.flow_id, begun.step
        for _ in range(20):
            kind_now = value(step.kind)
            if kind_now == "device-code":
                print("\n  Open:  %s\n  Code:  %s\n  (valid for %s s; waiting for you to approve...)\n" % (step.verification_uri, step.user_code, step.expires_in))
                if args.dry:
                    await login.cancel(AuthLoginCancelRequest(flow_id=flow))
                    print("dry run: cancelled")
                    break
                step = await login.advance(AuthLoginAdvanceRequest(flow_id=flow), timeout=(step.expires_in or 900) + 30)
            elif kind_now == "open-url":
                print("\n  Open this URL in a browser and sign in:\n  %s\n" % step.url)
                step = await login.advance(AuthLoginAdvanceRequest(flow_id=flow), timeout=900)
            elif kind_now == "input-required":
                answer = input("%s " % (step.prompt or "Input:"))
                step = await login.advance(AuthLoginAdvanceRequest(flow_id=flow, input=answer))
            elif kind_now in ("awaiting", "needs-interaction"):
                if step.message:
                    print(step.message)
                step = await login.advance(AuthLoginAdvanceRequest(flow_id=flow), timeout=900)
            elif kind_now == "completed":
                result = step.result
                print("login result: %s, host: %s" % (value(getattr(result, "status", None)), getattr(result, "host", None)))
                if value(getattr(result, "status", None)) == "needs-plaintext-consent":
                    print("The runtime found no secure store and asks before saving the sign-in as plain text. Send a photo; nothing was saved.")
                break
            elif kind_now == "error":
                print("login error: %s" % (step.message or step))
                break
            else:
                print("unexpected step: %s %s" % (kind_now, step))
                break
        await session.disconnect()
    auth = await client.get_auth_status()
    print("after: signed in = %s, way = %s" % (auth.is_authenticated, auth.auth_type))
    await client.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("github", "entra", "proxima"), default="github")
    parser.add_argument("--again", action="store_true")
    parser.add_argument("--dry", action="store_true", help="show the code, then cancel (for testing)")
    asyncio.run(main(parser.parse_args()))
