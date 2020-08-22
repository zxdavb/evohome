"""A CLI for the evohome_rf library.

evohome_rf is used to parse Honeywell's RAMSES-II packets, either via RF or from a file.
"""
import asyncio
import json
import sys

import click

from evohome import Gateway, GracefulExit

DEBUG_ADDR = "0.0.0.0"
DEBUG_PORT = 5678

# this is needed only when debugging the client
# import ptvsd
# ptvsd.enable_attach(address=(DEBUG_ADDR, DEBUG_PORT))
# ptvsd.wait_for_attach()

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option("-z", "--debug-mode", help="TBD", count=True)
@click.option("-r", "--reduce-processing", help="TBD", count=True)
@click.option("-c", "--config-file", help="TBD", type=click.Path())
@click.pass_context
def cli(ctx, **kwargs):
    """A CLI for the evohome_rf library."""
    # if kwargs["debug_mode"]:
    #     print(f"cli(): ctx.obj={ctx.obj}, kwargs={kwargs}")
    ctx.obj = kwargs


@click.command()
@click.argument("input-file", type=click.File("r"), default=sys.stdin)
@click.pass_obj
def parse(obj, **kwargs):
    """Parse a file for packets."""
    # if obj["debug_mode"]:
    #     print(f"parse(): obj={obj}, kwargs={kwargs}")
    debug_wrapper(**obj, **kwargs)


@click.command()
@click.argument("serial-port")
@click.option("-p", "--enable_probing", help="TBD", is_flag=True)
@click.option("-T", "--evofw-flag", help="TBD")
@click.option("-x", "--execute-cmd", help="e.g.: RQ 01:123456 1F09 00")
@click.option(
    "-o",
    "--packet-log",
    help="TBD",
    type=click.Path(),
    default="packet.log",
    show_default=True,
)
@click.pass_obj
def monitor(obj, **kwargs):
    """Monitor a serial port for packets."""
    # if obj["debug_mode"]:
    #     print(f"monitor(): obj={obj}, kwargs={kwargs}")
    debug_wrapper(**obj, **kwargs)


def debug_wrapper(config_file=None, **kwargs):
    # 1st: sort out any debug mode (a CLI-only parameter)...
    assert 0 <= kwargs["debug_mode"] <= 3

    if kwargs["debug_mode"] == 3:
        print("Additional logging enabled (debugging not enabled).")

    elif kwargs["debug_mode"] != 0:
        import ptvsd

        print(f"Debugging is enabled, listening on: {DEBUG_ADDR}:{DEBUG_PORT}.")
        ptvsd.enable_attach(address=(DEBUG_ADDR, DEBUG_PORT))

        if kwargs["debug_mode"] == 1:
            print(" - execution paused, waiting for debugger to attach...")
            ptvsd.wait_for_attach()
            print(" - debugger is now attached, continuing execution.")

    # 2nd: start with config file...
    config = {}
    if config_file is not None:
        with open(config_file) as json_data:
            config = json.load(json_data)

    config["config"] = config.get("config", {})

    # 3rd: the CLI overwrites the config file...
    for key in ("serial_port", "input_file", "reduce_processing", "packet_log"):
        config["config"][key] = kwargs.pop(key, None)

    if "enable_probing" in kwargs:
        config["config"]["disable_probing"] = not kwargs.pop("enable_probing")

    print("config", config)
    print("debug_flags", kwargs)

    asyncio.run(main(config=config, debug_flags=kwargs))


async def main(loop=None, config=None, debug_flags=None):

    # loop=asyncio.get_event_loop() causes: 'NoneType' object has no attribute 'serial'
    print("Starting evohome_rf...")

    if sys.platform == "win32":  # is better than os.name
        # ERROR:asyncio:Cancelling an overlapped future failed
        # future: ... cb=[BaseProactorEventLoop._loop_self_reading()]
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    gateway = None  # avoid possibly unbound error
    try:
        gateway = Gateway(loop=loop, config=config, debug_flags=debug_flags)
        task = asyncio.create_task(gateway.start())
        # await asyncio.sleep(20)
        # print(await gateway.evo.zones[0].name)
        await task

    except asyncio.CancelledError:
        print(" - exiting via: CancelledError (this is expected)")
    except GracefulExit:
        print(" - exiting via: GracefulExit")
    except KeyboardInterrupt:
        print(" - exiting via: KeyboardInterrupt")
    else:  # if no Exceptions raised, e.g. EOF when parsing
        print(" - exiting via: else-block (e.g. EOF when parsing)")

    if gateway.evo is not None:
        print(f"\r\nSchema[{gateway.evo.id}] = {json.dumps(gateway.evo.schema)}")
        print(f"\r\nParams[{gateway.evo.id}] = {json.dumps(gateway.evo.params)}")
        print(f"\r\nStatus[{gateway.evo.id}] = {json.dumps(gateway.evo.status)}")

    # else:
    print(f"\r\nSchema[gateway] = {json.dumps(gateway.schema)}")

    print("\r\nFinished evohome_rf.")


cli.add_command(monitor)
cli.add_command(parse)

if __name__ == "__main__":
    cli()
