#!/usr/bin/env python3
"""
Simple Cisco SD-WAN Certificate Automation
Uses Netmiko for better Viptela/SD-WAN CLI handling

Usage:
    # Manager actions:
    ./sdwan_automation.py manager --first-boot
    ./sdwan_automation.py manager --cert
    ./sdwan_automation.py manager --initial-config
    ./sdwan_automation.py manager --config-file myconfig.txt
    ./sdwan_automation.py manager --cert --config-file additional.txt

    # Validator actions (placeholder for now):
    ./sdwan_automation.py validator --first-boot
    ./sdwan_automation.py validator --cert
    ./sdwan_automation.py validator --initial-config
    ./sdwan_automation.py validator --config-file myconfig.txt

    # Controller actions (placeholder for now):
    ./sdwan_automation.py controller --first-boot
    ./sdwan_automation.py controller --cert
    ./sdwan_automation.py controller --initial-config
    ./sdwan_automation.py controller --config-file myconfig.txt
"""

import argparse
import sys

from components.sdwan_controller import run_controller_automation
from components.sdwan_manager import run_manager_automation
from components.sdwan_validator import run_validator_automation
from sdwan_config import CONFIG
from utils.logging import setup_logging
from utils.output import Output


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
        help="Run certificate automation (placeholder)",
    )
    validator_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial validator configuration (placeholder)",
    )
    validator_parser.add_argument(
        "--config-file",
        help="Configuration file to push to validator (placeholder)",
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
        help="Run certificate automation (placeholder)",
    )
    controller_parser.add_argument(
        "--initial-config",
        action="store_true",
        help="Push initial controller configuration (placeholder)",
    )
    controller_parser.add_argument(
        "--config-file",
        help="Configuration file to push to controller (placeholder)",
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
        out.banner("Cisco SD-WAN Automation Script")

        run_manager_automation(
            CONFIG.manager,
            initial_config=True,
            cert=True,
        )
        run_validator_automation(
            CONFIG.validator,
            initial_config=True,
            cert=True,
        )
        run_controller_automation(
            CONFIG.controller,
            initial_config=True,
            cert=True,
        )
        out.header("All Components Complete")
        out.success("First-boot automation finished for Manager, Validator, and Controller")
        return

    out.log_only(
        f"Run start component={args.component} "
        f"first_boot={args.first_boot} "
        f"initial_config={args.initial_config} "
        f"cert={args.cert} "
        f"config_file={getattr(args, 'config_file', None)}"
    )

    # If no action flags provided for the component, show help
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
            CONFIG.manager,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Manager Complete")
        out.success("Manager automation finished")
    elif args.component == "validator":
        run_validator_automation(
            CONFIG.validator,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Validator Complete")
        out.success("Validator automation finished")
    elif args.component == "controller":
        run_controller_automation(
            CONFIG.controller,
            initial_config=args.initial_config,
            cert=args.cert,
            config_file=args.config_file,
        )
        out.header("Controller Complete")
        out.success("Controller automation finished")


if __name__ == "__main__":
    main()
