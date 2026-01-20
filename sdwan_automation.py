#!/usr/bin/env python3
"""
Simple Cisco SD-WAN Certificate Automation
Uses Netmiko for better Viptela/SD-WAN CLI handling

Usage:
    # Components actions:
    ./sdwan_automation.py [manager, validator, controller] --first-boot
    ./sdwan_automation.py [manager, validator, controller] --cert
    ./sdwan_automation.py [manager, validator, controller] --initial-config
    ./sdwan_automation.py [manager, validator, controller] --config-file myconfig.txt
    ./sdwan_automation.py [manager, validator, controller] --cert --config-file additional.txt

    # Run first-boot on all components:
    ./sdwan_automation.py all

    # Show Manager status tables:
    ./sdwan_automation.py show devices

    # Call the sdwan SDK CLI directly using `sdk` and passing all arguments after it:
    ./sdwan_automation.py sdk show dev
"""

import argparse
import sys
import time
from pathlib import Path

import sdwan_config as settings
from components.sdwan_controller import run_controller_automation
from components.sdwan_edges import run_edges_automation
from components.sdwan_manager import run_manager_automation
from components.sdwan_validator import run_validator_automation
from utils.component_sync import reboot_out_of_sync_components
from utils.logging import setup_logging
from utils.manager_api_status import show_controller_status, show_edge_health_status
from utils.output import Output
from utils.sdwan_sdk import run_sdwan_cli


def main():
    """Main function to orchestrate the automation"""

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Cisco SD-WAN Certificate Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="component")

    manager_parser = subparsers.add_parser("manager", help="SD-WAN Manager tasks")
    manager_parser.set_defaults(_parser=manager_parser)
    manager_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )
    manager_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="First boot: push initial config and run certificate automation",
    )
    manager_parser.add_argument(
        "--cert",
        action="store_true",
        help="Run certificate automation",
    )
    manager_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial Manager configuration (sets password, routes, etc.)",
    )
    manager_parser.add_argument(
        "--config-file",
        help="Configuration file to push to Manager",
    )

    validator_parser = subparsers.add_parser("validator", help="Validator tasks")
    validator_parser.set_defaults(_parser=validator_parser)
    validator_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )
    validator_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="First boot: push initial config and run certificate automation",
    )
    validator_parser.add_argument(
        "--cert",
        action="store_true",
        help="Run certificate automation",
    )
    validator_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial validator configuration",
    )
    validator_parser.add_argument(
        "--config-file",
        help="Configuration file to push to validator",
    )

    controller_parser = subparsers.add_parser("controller", help="Controller tasks")
    controller_parser.set_defaults(_parser=controller_parser)
    controller_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )
    controller_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="First boot: push initial config and run certificate automation",
    )
    controller_parser.add_argument(
        "--cert",
        action="store_true",
        help="Run certificate automation",
    )
    controller_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial controller configuration",
    )
    controller_parser.add_argument(
        "--config-file",
        help="Configuration file to push to controller",
    )

    edges_parser = subparsers.add_parser("edges", help="Edge tasks")
    edges_parser.set_defaults(_parser=edges_parser)
    edges_parser.add_argument(
        "targets",
        help="Comma-separated edge names (edge1,edge2) or 'all'",
    )
    edges_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )
    edges_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="First boot: push initial config and run certificate automation",
    )
    edges_parser.add_argument(
        "--cert",
        action="store_true",
        help="Run certificate automation",
    )
    edges_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial edge configuration",
    )
    edges_parser.add_argument(
        "--config-file",
        help="Configuration file to push to edges",
    )

    all_parser = subparsers.add_parser(
        "all", help="Run first-boot on all components (manager, validator, controller)"
    )
    all_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )

    show_parser = subparsers.add_parser("show", help="Show Manager status tables")
    show_parser.set_defaults(_parser=show_parser)
    show_parser.add_argument(
        "resource",
        choices=["devices"],
        help="Status table to display",
    )
    show_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )

    sdk_parser = subparsers.add_parser(
        "sdk", help="Pass through commands to the Sastre SDK CLI"
    )
    sdk_parser.set_defaults(_parser=sdk_parser)
    sdk_parser.add_argument(
        "sdk_args",
        nargs=argparse.REMAINDER,
        help="Arguments to pass to the sdwan CLI",
    )
    sdk_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed device actions and file contents",
    )

    args = parser.parse_args()

    # If no arguments provided, show help
    if not args.component:
        parser.print_help()
        sys.exit(0)

    setup_logging(args.verbose)
    out = Output(__name__)

    # Handle "all" component - runs first-boot on everything
    if args.component == "all":
        out.log_only("Run start component=all (first-boot on all components)")
        out.banner("Cisco SD-WAN Full Automation Script")

        run_manager_automation(
            settings.manager,
            initial_config=True,
            cert=True,
        )
        out.spinner_wait(
            f"Waiting {settings.WAIT_BEFORE_AUTOMATING_VALIDATOR}s before starting Validator automation...",
            settings.WAIT_BEFORE_AUTOMATING_VALIDATOR,
        )
        run_validator_automation(
            settings.validator,
            initial_config=True,
            cert=True,
        )
        out.spinner_wait(
            f"Waiting {settings.WAIT_BEFORE_AUTOMATING_CONTROLLER}s before starting Controller automation...",
            settings.WAIT_BEFORE_AUTOMATING_CONTROLLER,
        )
        run_controller_automation(
            settings.controller,
            initial_config=True,
            cert=True,
        )
        show_controller_status(settings.manager, out=out)
        edge_configs = [
            value
            for value in vars(settings).values()
            if isinstance(value, settings.EdgeConfig)
        ]
        if not edge_configs:
            out.warning("No edge configs found in sdwan_config.py.")
        else:
            run_edges_automation(
                edge_configs,
                initial_config=True,
                cert=True,
            )
        out.header("All Components Complete")
        out.success(
            "First-boot automation finished for Manager, Validator, Controller, and Edges"
        )
        reboot_out_of_sync_components(settings.manager)
        show_edge_health_status(settings.manager, out=out)
        return

    if args.component == "show":
        out.log_only(f"Run start component=show resource={args.resource}")
    elif args.component == "sdk":
        out.log_only(f"Run start component=sdk args={args.sdk_args}")
    elif args.component == "edges":
        out.log_only(
            f"Run start component=edges targets={args.targets} "
            f"first_boot={args.first_boot} "
            f"initial_config={args.initial_config} "
            f"cert={args.cert} "
            f"config_file={getattr(args, 'config_file', None)}"
        )
    else:
        out.log_only(
            f"Run start component={args.component} "
            f"first_boot={args.first_boot} "
            f"initial_config={args.initial_config} "
            f"cert={args.cert} "
            f"config_file={getattr(args, 'config_file', None)}"
        )

    # If no action flags provided for the component, show help
    if args.component == "show":
        out.banner("Cisco SD-WAN Show Information")
        if args.resource == "devices":
            show_controller_status(settings.manager, out=out)
            show_edge_health_status(settings.manager, out=out)
        return
    if args.component == "edges":
        has_config_file = hasattr(args, "config_file") and args.config_file
        if not any([args.first_boot, args.cert, args.initial_config, has_config_file]):
            args._parser.print_help()
            sys.exit(0)
        if args.first_boot:
            args.initial_config = True
            args.cert = True

        targets = [t.strip() for t in args.targets.split(",") if t.strip()]
        if not targets:
            out.error("No edge targets provided.")
            sys.exit(1)

        if len(targets) == 1 and targets[0].lower() == "all":
            edge_configs = [
                value
                for name, value in vars(settings).items()
                if name.startswith("edge") and isinstance(value, settings.EdgeConfig)
            ]
            if not edge_configs:
                out.error("No edge configs found in sdwan_config.py.")
                sys.exit(1)
        else:
            edge_configs = []
            for target in targets:
                config = getattr(settings, target, None)
                if config is None:
                    out.error(f"Unknown edge target: {target}")
                    sys.exit(1)
                edge_configs.append(config)

        run_edges_automation(
            edge_configs,
            initial_config=args.initial_config,
            config_file=args.config_file,
            cert=args.cert,
        )
        out.header("Edges Complete")
        out.success("Edge automation finished")
        return
    if args.component == "sdk":
        if not args.sdk_args:
            out.warning("No SDK arguments provided. Example: sdk show device")
            return
        result = run_sdwan_cli(settings, args.sdk_args)
        if result != 0:
            raise SystemExit(result)
        return

    has_config_file = hasattr(args, "config_file") and args.config_file
    if not any([args.first_boot, args.cert, args.initial_config, has_config_file]):
        args._parser.print_help()
        sys.exit(0)

    # Expand --first-boot into --initial-config + --cert
    if args.first_boot:
        args.initial_config = True
        args.cert = True

    out.banner("Cisco SD-WAN Automation Script")

    if args.component == "manager":
        run_manager_automation(
            settings.manager,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Manager Complete")
        out.success("Manager automation finished")
    elif args.component == "validator":
        run_validator_automation(
            settings.validator,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Validator Complete")
        out.success("Validator automation finished")
    elif args.component == "controller":
        run_controller_automation(
            settings.controller,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Controller Complete")
        out.success("Controller automation finished")

    show_controller_status(settings.manager, out=out)


if __name__ == "__main__":
    main()
