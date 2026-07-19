#!/usr/bin/env bash

set -Eeuo pipefail

readonly REPOSITORY_URL="${YAM_INITIALIZER_REPOSITORY_URL:-https://github.com/godbrigero/YamDualArmController.git}"
readonly PROJECT_DIRECTORY="$PWD"

temporary_directory=""
uv_executable=""

require_uv() {
    if ! uv_executable="$(command -v uv)"; then
        printf 'UV is required but is not installed. Aborting before project setup.\n' >&2
        printf 'Install UV from: https://docs.astral.sh/uv/getting-started/installation/\n' >&2
        return 1
    fi
}

remove_temporary_directory() {
    if [[ -n "$temporary_directory" && -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi

    temporary_directory=""
}

cleanup() {
    local exit_status=$?

    trap - EXIT

    remove_temporary_directory

    exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

sync_managed_file() {
    local source_file=$1
    local target_file=$2

    if [[ -d "$target_file" ]]; then
        printf 'Cannot update managed file because the target is a directory: %s\n' "$target_file" >&2
        return 1
    fi

    if [[ -f "$target_file" ]] && cmp -s "$source_file" "$target_file"; then
        printf 'Already up to date: %s\n' "$target_file"
        return
    fi

    if [[ -e "$target_file" ]]; then
        printf 'Updating: %s\n' "$target_file"
    else
        printf 'Installing: %s\n' "$target_file"
    fi

    mkdir -p "$(dirname "$target_file")"
    cp -p "$source_file" "$target_file"
}

sync_managed_directory() {
    local source_directory=$1
    local target_directory=$2

    if [[ -e "$target_directory" && ! -d "$target_directory" ]]; then
        printf 'Cannot update managed directory because the target is not a directory: %s\n' "$target_directory" >&2
        return 1
    fi

    if [[ -d "$target_directory" ]] && diff -qr "$source_directory" "$target_directory" >/dev/null; then
        printf 'Already up to date: %s/\n' "$target_directory"
        return
    fi

    if [[ -d "$target_directory" ]]; then
        printf 'Updating: %s/\n' "$target_directory"
        rm -rf -- "$target_directory"
    else
        printf 'Installing: %s/\n' "$target_directory"
    fi

    mkdir -p "$target_directory"
    cp -R "$source_directory/." "$target_directory/"
}

run_project_initialization() {
    local repository_directory=$1
    local project_directory=$2
    local source_calibration_script="$repository_directory/scripts/calibrate.py"
    local source_bridge_directory="$repository_directory/leader_yam_bridge"
    local source_teleoperation_directory="$repository_directory/teleoperation"
    local target_scripts_directory="$project_directory/scripts"
    local target_bridge_directory="$project_directory/leader_yam_bridge"
    local target_teleoperation_directory="$project_directory/teleoperation"

    if [[ ! -f "$source_calibration_script" ]]; then
        printf 'Missing required file in cloned repository: %s\n' "$source_calibration_script" >&2
        return 1
    fi

    if [[ ! -d "$source_bridge_directory" ]]; then
        printf 'Missing required directory in cloned repository: %s\n' "$source_bridge_directory" >&2
        return 1
    fi

    if [[ ! -f "$source_teleoperation_directory/__main__.py" ]]; then
        printf 'Missing required file in cloned repository: %s\n' "$source_teleoperation_directory/__main__.py" >&2
        return 1
    fi

    sync_managed_file "$source_calibration_script" "$target_scripts_directory/calibrate.py"
    sync_managed_directory "$source_bridge_directory" "$target_bridge_directory"
    sync_managed_directory "$source_teleoperation_directory" "$target_teleoperation_directory"

    if [[ -d "$project_directory/outputs" ]]; then
        printf 'Already present: %s/\n' "$project_directory/outputs"
    else
        printf 'Creating: %s/\n' "$project_directory/outputs"
        mkdir -p "$project_directory/outputs"
    fi
}

configure_uv_project() {
    local project_directory=$1

    printf 'Configuring UV project dependencies...\n'

    if [[ ! -f "$project_directory/pyproject.toml" ]]; then
        "$uv_executable" init \
            --bare \
            --name yam-teleoperation \
            --python '>=3.12,<3.13' \
            --no-workspace \
            "$project_directory"
    fi

    (
        cd "$project_directory"
        "$uv_executable" add \
            --no-workspace \
            --upgrade-package numpy \
            --upgrade-package feetech-servo-sdk \
            --upgrade-package i2rt \
            numpy \
            feetech-servo-sdk \
            'i2rt @ git+https://github.com/i2rt-robotics/i2rt.git'
    )
}

show_calibration_prompt() {
    local message='Project setup is complete. Run "uv run scripts/calibrate.py" to calibrate the servos and create the calibration JSON inside outputs/. Then start teleoperation with "uv run -m teleoperation".'

    if [[ "${YAM_INITIALIZER_SKIP_PROMPT:-0}" == "1" ]]; then
        printf '\n%s\n' "$message"
        return
    fi

    if command -v osascript >/dev/null 2>&1; then
        osascript -e 'display dialog "Project setup is complete." & return & return & "First run: uv run scripts/calibrate.py" & return & "Then run: uv run -m teleoperation" & return & return & "Calibration creates its JSON inside outputs/." with title "YAM Project Setup" buttons {"OK"} default button "OK" with icon note'
    elif command -v zenity >/dev/null 2>&1; then
        zenity --info --title='YAM Project Setup' --ok-label='OK' --text="$message"
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --title 'YAM Project Setup' --msgbox "$message"
    elif command -v whiptail >/dev/null 2>&1; then
        whiptail --title 'YAM Project Setup' --msgbox "$message" 12 72
    elif command -v dialog >/dev/null 2>&1; then
        dialog --title 'YAM Project Setup' --msgbox "$message" 12 72
    elif [[ -t 0 && -t 1 ]]; then
        printf '\n%s\n\n' "$message"
        read -r -p 'Press Enter to select [ OK ]... ' _
    else
        printf '\n%s\n' "$message"
    fi
}

main() {
    require_uv

    temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/yam-project-initializer.XXXXXX")"
    local cloned_repository_directory="$temporary_directory/YamDualArmController"

    printf 'Cloning YamDualArmController...\n'
    git clone --depth 1 "$REPOSITORY_URL" "$cloned_repository_directory"

    run_project_initialization "$cloned_repository_directory" "$PROJECT_DIRECTORY"
    configure_uv_project "$PROJECT_DIRECTORY"
    remove_temporary_directory

    printf 'Project initialization complete.\n'
    show_calibration_prompt
}

main "$@"
