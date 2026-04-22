#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GIMP MCP Plugin - Model Context Protocol integration for GIMP
Provides bitmap extraction and metadata access functionality
"""

import gi
gi.require_version('Gimp', '3.0')

from gi.repository import Gimp
from gi.repository import GLib
from gi.repository import GObject

import io
import sys
import json
import socket
import traceback
import threading
import base64
import tempfile
import os
import platform
import signal

# Constants for configuration and thresholds
LARGE_SCALING_THRESHOLD = 4.0  # Warn if scaling ratio exceeds this value
MAX_REGION_SIZE = 8192  # Maximum region dimension in pixels
DEFAULT_TIMEOUT_SECONDS = 30  # Default timeout for operations


def N_(message): return message
def _(message): return GLib.dgettext(None, message)


def exec_and_get_results(command, context):
    buffer = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = buffer
    exec(command, context)
    sys.stdout = original_stdout
    output = buffer.getvalue()
    return output


class MCPPlugin(Gimp.PlugIn):
    def __init__(self, host='localhost', port=9877):
        super().__init__()
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None
        self.context = {}
        exec("from gi.repository import Gimp", self.context)
        self.auto_disconnect_client = True
        # name → image_index mapping for begin/commit/rollback_transaction
        self._active_transactions = {}

    def do_set_i18n(self, procname):
        # Plugin has no translations; tell GIMP so it stops logging
        # "catalog directory does not exist" for every registered procedure.
        return False

    def do_query_procedures(self):
        """Register the plugin procedures."""
        return ["plug-in-mcp-server", "plug-in-mcp-check", "plug-in-mcp-restart"]

    def do_create_procedure(self, name):
        """Define the procedure properties."""
        if name == "plug-in-mcp-check":
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, self._run_check, None)
            procedure.set_menu_label(_("Check MCP Server"))
            procedure.set_documentation(_("Check whether the MCP server is running"),
                                        _("Prints MCP server status to the GIMP console"),
                                        name)
            procedure.set_attribution("Viesar Lab", "Viesar Lab", "2026")
            procedure.add_enum_argument("run-mode", _("Run mode"), _("The run mode"),
                                        Gimp.RunMode, Gimp.RunMode.INTERACTIVE,
                                        GObject.ParamFlags.READWRITE)
            procedure.add_menu_path('<Image>/Tools/MCP')
            return procedure

        if name == "plug-in-mcp-restart":
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, self._run_restart, None)
            procedure.set_menu_label(_("Restart MCP Server"))
            procedure.set_documentation(_("Restart the MCP server socket"),
                                        _("Drops and re-binds the MCP server socket on port 9877"),
                                        name)
            procedure.set_attribution("Viesar Lab", "Viesar Lab", "2026")
            procedure.add_enum_argument("run-mode", _("Run mode"), _("The run mode"),
                                        Gimp.RunMode, Gimp.RunMode.INTERACTIVE,
                                        GObject.ParamFlags.READWRITE)
            procedure.add_menu_path('<Image>/Tools/MCP')
            return procedure

        # Default: plug-in-mcp-server
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_menu_label(_("Start MCP Server"))
        procedure.set_documentation(_("Starts an MCP server to control GIMP externally"),
                                    _("Starts an MCP server to control GIMP externally"),
                                    name)
        procedure.set_attribution("Viesar Lab", "Viesar Lab", "2026")
        procedure.add_enum_argument("run-mode", _("Run mode"), _("The run mode"),
                                    Gimp.RunMode, Gimp.RunMode.INTERACTIVE,
                                    GObject.ParamFlags.READWRITE)
        procedure.add_menu_path('<Image>/Tools/MCP')
        return procedure

    def _run_check(self, procedure, config, run_data):
        """Menu action: print server status."""
        status = "RUNNING" if self.running else "STOPPED"
        print(f"[MCP] Server status: {status} on port {self.port}")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    def _run_restart(self, procedure, config, run_data):
        """Menu action: restart the server socket."""
        result = self._restart_server()
        print(f"[MCP] Restart result: {result}")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    def shutdown_server(self, signum=None, frame=None):
        """Gracefully shutdown the server."""
        print(f"Shutdown signal received (signal: {signum}), closing MCP server...")
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        if hasattr(self, '_glib_loop') and self._glib_loop:
            self._glib_loop.quit()

    def _start_server_thread(self):
        """Core server loop — runs in a background thread."""
        self.running = True
        try:
            print("Creating socket...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.settimeout(1.0)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            print(f"GimpMCP server started on {self.host}:{self.port}")

            while self.running:
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")
                except socket.timeout:
                    continue
                except OSError:
                    break
                client_thread = threading.Thread(target=self._handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()

            print("MCP server shutting down...")
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            print("MCP server stopped")
        except Exception as e:
            print(f"Error in MCP server thread: {str(e)}")
            self.running = False

    def run(self, procedure, config, run_data):
        """Menu handler: start the server."""
        if self.running:
            print("MCP Server is already running")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

        signal.signal(signal.SIGTERM, self.shutdown_server)
        signal.signal(signal.SIGINT, self.shutdown_server)

        # Server socket runs in a background thread
        server_thread = threading.Thread(target=self._start_server_thread, daemon=True)
        server_thread.start()

        # GLib main loop runs in the main thread — required for GIMP API calls
        # (all Gimp.* calls go over the wire protocol which needs GLib to dispatch)
        self._glib_loop = GLib.MainLoop()
        self._glib_loop.run()

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    def _handle_client(self, client):
        """Handle connected client"""
        # print("Client handler started")
        buffer = b''

        # Receive data in chunks to handle larger payloads
        while True:
            data = client.recv(4096)
            # print(f"Received data: {data}")
            if not data:
                break
            buffer += data
            
            # Check if we have a complete message
            # For simplicity, assume messages end with newline or are complete JSON
            try:
                if isinstance(buffer, (bytes, bytearray)):
                    request = buffer.decode('utf-8')
                else:
                    request = str(buffer)
                
                # Try to parse as JSON to see if complete
                if request.strip():
                    json.loads(request)  # This will raise if incomplete
                    break
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Continue receiving if JSON is incomplete
                continue
        
        if not buffer:
            print("Client disconnected")
            return

        if isinstance(buffer, (bytes, bytearray)):
            request = buffer.decode('utf-8')
        else:
            request = str(buffer)
        
        # print(f"Parsed request: {request}")
        response = self.execute_command(request)
        print(f"response type: {type(response)}")
        
        if isinstance(response, dict):
            response_str = json.dumps(response)
        else:
            response_str = str(response)
            
        # Send response in chunks for large data
        response_bytes = response_str.encode('utf-8')
        bytes_sent = 0
        while bytes_sent < len(response_bytes):
            chunk = response_bytes[bytes_sent:bytes_sent + 8192]
            client.sendall(chunk)
            bytes_sent += len(chunk)
            
        if self.auto_disconnect_client:
            client.close()
        return

    def _normalize_exec_lines(self, lines):
        """Collapse indented-continuation lines back into their leading block.

        Lines whose first character is whitespace are appended to the previous
        entry with a newline joiner, so that
            ["def foo():", "    return 1"]
        becomes
            ["def foo():\\n    return 1"]
        and exec's as a single top-level statement. Lines that don't start
        with whitespace are left as their own entries, preserving the
        per-entry output ordering for scripts that already work.
        """
        if not isinstance(lines, list):
            return lines
        out = []
        for line in lines:
            if (isinstance(line, str) and line
                    and line[0] in (' ', '\t')
                    and out
                    and isinstance(out[-1], str)):
                out[-1] = out[-1] + '\n' + line
            else:
                out.append(line)
        return out

    def execute_command(self, request):
        """Execute commands in GIMP's main thread."""
        try:
            if request == "disable_auto_disconnect":
                self.auto_disconnect_client = False
                return {"status": "success", "results": "OK"}
            j = json.loads(request)
            if "type" in j and j["type"] == "get_image_bitmap":
                params = j.get("params", {})
                return self._get_current_image_bitmap(params)
            elif "type" in j and j["type"] == "get_image_metadata":
                return self._get_current_image_metadata()
            elif "type" in j and j["type"] == "get_gimp_info":
                return self._get_gimp_info()
            elif "type" in j and j["type"] == "get_context_state":
                return self._get_context_state()
            elif "type" in j and j["type"] == "check_server":
                return {"status": "success", "results": {"running": True, "port": self.port}}
            elif "type" in j and j["type"] == "restart_server":
                return self._restart_server()
            elif "type" in j and j["type"] == "new_canvas":
                params = j.get("params", {})
                return self._new_canvas(params)
            # ── Category 1: File Operations ──────────────────────────────────
            elif "type" in j and j["type"] == "open_image":
                return self._open_image(j.get("params", {}))
            elif "type" in j and j["type"] == "save_xcf":
                return self._save_xcf(j.get("params", {}))
            elif "type" in j and j["type"] == "duplicate_image":
                return self._duplicate_image(j.get("params", {}))
            elif "type" in j and j["type"] == "load_image_as_layer":
                return self._load_image_as_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "export_image":
                return self._export_image(j.get("params", {}))
            elif "type" in j and j["type"] == "batch_export":
                return self._batch_export(j.get("params", {}))
            # ── Category 2: Image Adjustments ────────────────────────────────
            elif "type" in j and j["type"] == "auto_levels":
                return self._auto_levels(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_levels":
                return self._adjust_levels(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_curves":
                return self._adjust_curves(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_threshold":
                return self._adjust_threshold(j.get("params", {}))
            elif "type" in j and j["type"] == "posterize":
                return self._posterize(j.get("params", {}))
            elif "type" in j and j["type"] == "color_temperature":
                return self._color_temperature(j.get("params", {}))
            elif "type" in j and j["type"] == "exposure":
                return self._exposure(j.get("params", {}))
            elif "type" in j and j["type"] == "shadows_highlights":
                return self._shadows_highlights(j.get("params", {}))
            elif "type" in j and j["type"] == "black_and_white":
                return self._black_and_white(j.get("params", {}))
            elif "type" in j and j["type"] == "photo_filter":
                return self._photo_filter(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_unsharp_mask":
                return self._apply_unsharp_mask(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_motion_blur":
                return self._apply_motion_blur(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_lens_blur":
                return self._apply_lens_blur(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_bokeh":
                return self._apply_bokeh(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_despeckle":
                return self._apply_despeckle(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_color_to_alpha":
                return self._apply_color_to_alpha(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_bump_map":
                return self._apply_bump_map(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_displacement":
                return self._apply_displacement(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_oilify":
                return self._apply_oilify(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_cartoon":
                return self._apply_cartoon(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_waterpixels":
                return self._apply_waterpixels(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_seamless_tile":
                return self._apply_seamless_tile(j.get("params", {}))
            elif "type" in j and j["type"] == "set_foreground":
                return self._set_foreground(j.get("params", {}))
            elif "type" in j and j["type"] == "set_background":
                return self._set_background(j.get("params", {}))
            elif "type" in j and j["type"] == "swap_colors":
                return self._swap_colors(j.get("params", {}))
            elif "type" in j and j["type"] == "get_average_color":
                return self._get_average_color(j.get("params", {}))
            elif "type" in j and j["type"] == "get_dominant_colors":
                return self._get_dominant_colors(j.get("params", {}))
            elif "type" in j and j["type"] == "load_palette":
                return self._load_palette(j.get("params", {}))
            elif "type" in j and j["type"] == "save_palette":
                return self._save_palette(j.get("params", {}))
            elif "type" in j and j["type"] == "list_palettes":
                return self._list_palettes(j.get("params", {}))
            elif "type" in j and j["type"] == "get_palette_color":
                return self._get_palette_color(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_color_profile":
                return self._apply_color_profile(j.get("params", {}))
            elif "type" in j and j["type"] == "convert_to_profile":
                return self._convert_to_profile(j.get("params", {}))
            elif "type" in j and j["type"] == "assign_profile":
                return self._assign_profile(j.get("params", {}))
            elif "type" in j and j["type"] == "get_current_profile":
                return self._get_current_profile(j.get("params", {}))
            elif "type" in j and j["type"] == "list_brushes":
                return self._list_brushes(j.get("params", {}))
            elif "type" in j and j["type"] == "list_dynamics":
                return self._list_dynamics(j.get("params", {}))
            elif "type" in j and j["type"] == "list_patterns":
                return self._list_patterns(j.get("params", {}))
            elif "type" in j and j["type"] == "list_gradients":
                return self._list_gradients(j.get("params", {}))
            elif "type" in j and j["type"] == "list_pdb_procedures":
                return self._list_pdb_procedures(j.get("params", {}))
            elif "type" in j and j["type"] == "create_brush_from_selection":
                return self._create_brush_from_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "create_pattern_from_selection":
                return self._create_pattern_from_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_brush":
                return self._delete_brush(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_pattern":
                return self._delete_pattern(j.get("params", {}))
            elif "type" in j and j["type"] == "add_guide":
                return self._add_guide(j.get("params", {}))
            elif "type" in j and j["type"] == "list_guides":
                return self._list_guides(j.get("params", {}))
            elif "type" in j and j["type"] == "remove_guide":
                return self._remove_guide(j.get("params", {}))
            elif "type" in j and j["type"] == "remove_all_guides":
                return self._remove_all_guides(j.get("params", {}))
            elif "type" in j and j["type"] == "set_grid":
                return self._set_grid(j.get("params", {}))
            elif "type" in j and j["type"] == "get_grid":
                return self._get_grid(j.get("params", {}))
            elif "type" in j and j["type"] == "toggle_grid_visible":
                return self._toggle_grid_visible(j.get("params", {}))
            elif "type" in j and j["type"] == "snap_to_grid":
                return self._snap_to_grid(j.get("params", {}))
            elif "type" in j and j["type"] == "snap_to_guides":
                return self._snap_to_guides(j.get("params", {}))
            elif "type" in j and j["type"] == "snap_to_canvas_edges":
                return self._snap_to_canvas_edges(j.get("params", {}))
            elif "type" in j and j["type"] == "add_sample_point":
                return self._add_sample_point(j.get("params", {}))
            elif "type" in j and j["type"] == "list_sample_points":
                return self._list_sample_points(j.get("params", {}))
            elif "type" in j and j["type"] == "remove_sample_point":
                return self._remove_sample_point(j.get("params", {}))
            # ── Category 16: Extended Export ──────────────────────────────────
            elif "type" in j and j["type"] == "paste_from_clipboard":
                return self._paste_from_clipboard(j.get("params", {}))
            elif "type" in j and j["type"] == "copy_selection_to_clipboard":
                return self._copy_selection_to_clipboard(j.get("params", {}))
            elif "type" in j and j["type"] == "copy_layer_to_clipboard":
                return self._copy_layer_to_clipboard(j.get("params", {}))
            elif "type" in j and j["type"] == "export_webp":
                return self._export_webp(j.get("params", {}))
            elif "type" in j and j["type"] == "export_psd":
                return self._export_psd(j.get("params", {}))
            elif "type" in j and j["type"] == "import_psd":
                return self._import_psd(j.get("params", {}))
            elif "type" in j and j["type"] == "export_tiff":
                return self._export_tiff(j.get("params", {}))
            elif "type" in j and j["type"] == "export_hdr":
                return self._export_hdr(j.get("params", {}))
            elif "type" in j and j["type"] == "export_exr":
                return self._export_exr(j.get("params", {}))
            elif "type" in j and j["type"] == "export_gif_animation":
                return self._export_gif_animation(j.get("params", {}))
            elif "type" in j and j["type"] == "export_animated_sprite_strip":
                return self._export_animated_sprite_strip(j.get("params", {}))
            # ── Category 17: Scripting / Macros ───────────────────────────────
            elif "type" in j and j["type"] == "run_pdb_procedure":
                return self._run_pdb_procedure(j.get("params", {}))
            elif "type" in j and j["type"] == "run_script_fu":
                return self._run_script_fu(j.get("params", {}))
            elif "type" in j and j["type"] == "record_macro":
                return self._record_macro(j.get("params", {}))
            elif "type" in j and j["type"] == "stop_recording":
                return self._stop_recording(j.get("params", {}))
            elif "type" in j and j["type"] == "replay_macro":
                return self._replay_macro(j.get("params", {}))
            elif "type" in j and j["type"] == "list_macros":
                return self._list_macros(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_macro":
                return self._delete_macro(j.get("params", {}))
            # ── Category 18: Sessions ─────────────────────────────────────────
            elif "type" in j and j["type"] == "save_workspace":
                return self._save_workspace(j.get("params", {}))
            elif "type" in j and j["type"] == "load_workspace":
                return self._load_workspace(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_brightness_contrast":
                return self._adjust_brightness_contrast(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_hue_saturation":
                return self._adjust_hue_saturation(j.get("params", {}))
            elif "type" in j and j["type"] == "adjust_color_balance":
                return self._adjust_color_balance(j.get("params", {}))
            elif "type" in j and j["type"] == "sharpen":
                return self._sharpen(j.get("params", {}))
            elif "type" in j and j["type"] == "blur":
                return self._blur(j.get("params", {}))
            elif "type" in j and j["type"] == "denoise":
                return self._denoise(j.get("params", {}))
            elif "type" in j and j["type"] == "desaturate":
                return self._desaturate(j.get("params", {}))
            elif "type" in j and j["type"] == "invert_colors":
                return self._invert_colors(j.get("params", {}))
            # ── Category 3: Resize & Transform ───────────────────────────────
            elif "type" in j and j["type"] == "scale_image":
                return self._scale_image(j.get("params", {}))
            elif "type" in j and j["type"] == "scale_to_fit":
                return self._scale_to_fit(j.get("params", {}))
            elif "type" in j and j["type"] == "crop_to_selection":
                return self._crop_to_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "crop_to_rect":
                return self._crop_to_rect(j.get("params", {}))
            elif "type" in j and j["type"] == "rotate_image":
                return self._rotate_image(j.get("params", {}))
            elif "type" in j and j["type"] == "flip_image":
                return self._flip_image(j.get("params", {}))
            elif "type" in j and j["type"] == "resize_canvas":
                return self._resize_canvas(j.get("params", {}))
            # ── Category 4: Selections ────────────────────────────────────────
            elif "type" in j and j["type"] == "select_rectangle":
                return self._select_rectangle(j.get("params", {}))
            elif "type" in j and j["type"] == "select_ellipse":
                return self._select_ellipse(j.get("params", {}))
            elif "type" in j and j["type"] == "select_by_color":
                return self._select_by_color(j.get("params", {}))
            elif "type" in j and j["type"] == "select_all":
                return self._select_all(j.get("params", {}))
            elif "type" in j and j["type"] == "select_none":
                return self._select_none(j.get("params", {}))
            elif "type" in j and j["type"] == "invert_selection":
                return self._invert_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "modify_selection":
                return self._modify_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "alpha_to_selection":
                return self._alpha_to_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "fuzzy_select":
                return self._fuzzy_select(j.get("params", {}))
            # ── Category 5: Layer Operations ──────────────────────────────────
            elif "type" in j and j["type"] == "create_layer":
                return self._create_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "duplicate_layer":
                return self._duplicate_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_layer":
                return self._delete_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "rename_layer":
                return self._rename_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "set_layer_properties":
                return self._set_layer_properties(j.get("params", {}))
            elif "type" in j and j["type"] == "reorder_layer":
                return self._reorder_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "transform_layer":
                return self._transform_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "add_layer_mask":
                return self._add_layer_mask(j.get("params", {}))
            elif "type" in j and j["type"] == "remove_layer_mask":
                return self._remove_layer_mask(j.get("params", {}))
            elif "type" in j and j["type"] == "threshold_layer_mask":
                return self._threshold_layer_mask(j.get("params", {}))
            elif "type" in j and j["type"] == "flatten_image":
                return self._flatten_image(j.get("params", {}))
            elif "type" in j and j["type"] == "merge_visible_layers":
                return self._merge_visible_layers(j.get("params", {}))
            elif "type" in j and j["type"] == "list_layers":
                return self._list_layers(j.get("params", {}))
            # ── Category 6: Color & Paint ─────────────────────────────────────
            elif "type" in j and j["type"] == "fill_layer":
                return self._fill_layer(j.get("params", {}))
            elif "type" in j and j["type"] == "fill_selection":
                return self._fill_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "set_colors":
                return self._set_colors(j.get("params", {}))
            elif "type" in j and j["type"] == "draw_line":
                return self._draw_line(j.get("params", {}))
            elif "type" in j and j["type"] == "draw_rectangle":
                return self._draw_rectangle(j.get("params", {}))
            elif "type" in j and j["type"] == "draw_ellipse":
                return self._draw_ellipse(j.get("params", {}))
            elif "type" in j and j["type"] == "fill_rectangle":
                return self._fill_rectangle(j.get("params", {}))
            elif "type" in j and j["type"] == "fill_ellipse":
                return self._fill_ellipse(j.get("params", {}))
            elif "type" in j and j["type"] == "gradient_fill":
                return self._gradient_fill(j.get("params", {}))
            elif "type" in j and j["type"] == "paint_stroke":
                return self._paint_stroke(j.get("params", {}))
            # ── Category 7: Text ──────────────────────────────────────────────
            elif "type" in j and j["type"] == "add_text":
                return self._add_text(j.get("params", {}))
            elif "type" in j and j["type"] == "edit_text":
                return self._edit_text(j.get("params", {}))
            elif "type" in j and j["type"] == "list_fonts":
                return self._list_fonts(j.get("params", {}))
            # ── Category 8: Filters & Effects ────────────────────────────────
            elif "type" in j and j["type"] == "apply_drop_shadow":
                return self._apply_drop_shadow(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_gaussian_blur":
                return self._apply_gaussian_blur(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_pixelate":
                return self._apply_pixelate(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_emboss":
                return self._apply_emboss(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_vignette":
                return self._apply_vignette(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_noise":
                return self._apply_noise(j.get("params", {}))
            elif "type" in j and j["type"] == "apply_filter":
                return self._apply_filter(j.get("params", {}))
            # ── Category 9: Export Pipelines ──────────────────────────────────
            elif "type" in j and j["type"] == "export_icon_sizes":
                return self._export_icon_sizes(j.get("params", {}))
            elif "type" in j and j["type"] == "export_web_optimized":
                return self._export_web_optimized(j.get("params", {}))
            elif "type" in j and j["type"] == "batch_resize":
                return self._batch_resize(j.get("params", {}))
            elif "type" in j and j["type"] == "export_sprite_sheet":
                return self._export_sprite_sheet(j.get("params", {}))
            elif "type" in j and j["type"] == "export_social_media_kit":
                return self._export_social_media_kit(j.get("params", {}))
            # ── Category 10: Utility ──────────────────────────────────────────
            elif "type" in j and j["type"] == "list_images":
                return self._list_images(j.get("params", {}))
            elif "type" in j and j["type"] == "set_active_image":
                return self._set_active_image(j.get("params", {}))
            elif "type" in j and j["type"] == "undo":
                return self._undo(j.get("params", {}))
            elif "type" in j and j["type"] == "redo":
                return self._redo(j.get("params", {}))
            elif "type" in j and j["type"] == "convert_color_mode":
                return self._convert_color_mode(j.get("params", {}))
            elif "type" in j and j["type"] == "close_image":
                return self._close_image(j.get("params", {}))
            elif "type" in j and j["type"] == "get_selection_bounds":
                return self._get_selection_bounds(j.get("params", {}))
            elif "type" in j and j["type"] == "get_pixel_color":
                return self._get_pixel_color(j.get("params", {}))
            elif "type" in j and j["type"] == "get_histogram":
                return self._get_histogram(j.get("params", {}))
            elif "type" in j and j["type"] == "warp_region":
                return self._warp_region(j.get("params", {}))
            elif "type" in j and j["type"] == "get_canvas_info":
                return self._get_canvas_info(j.get("params", {}))
            elif "type" in j and j["type"] == "begin_transaction":
                return self._begin_transaction(j.get("params", {}))
            elif "type" in j and j["type"] == "commit_transaction":
                return self._commit_transaction(j.get("params", {}))
            elif "type" in j and j["type"] == "rollback_transaction":
                return self._rollback_transaction(j.get("params", {}))
            elif "type" in j and j["type"] == "get_layer_thumbnail":
                return self._get_layer_thumbnail(j.get("params", {}))
            elif "type" in j and j["type"] == "batch":
                return self._batch(j.get("params", {}))
            # ── Category 11: Discovery (3.2 migration helpers) ───────────────
            elif "type" in j and j["type"] == "get_pdb_procedure_info":
                return self._get_pdb_procedure_info(j.get("params", {}))
            elif "type" in j and j["type"] == "list_gegl_operations":
                return self._list_gegl_operations(j.get("params", {}))
            elif "type" in j and j["type"] == "list_blend_modes":
                return self._list_blend_modes(j.get("params", {}))
            # ── Category 12: Paths ────────────────────────────────────────────
            elif "type" in j and j["type"] == "path_create":
                return self._path_create(j.get("params", {}))
            elif "type" in j and j["type"] == "path_to_selection":
                return self._path_to_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "path_stroke":
                return self._path_stroke(j.get("params", {}))
            elif "type" in j and j["type"] == "import_svg_as_path":
                return self._import_svg_as_path(j.get("params", {}))
            elif "type" in j and j["type"] == "list_paths":
                return self._list_paths(j.get("params", {}))
            elif "type" in j and j["type"] == "rename_path":
                return self._rename_path(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_path":
                return self._delete_path(j.get("params", {}))
            elif "type" in j and j["type"] == "set_path_visible":
                return self._set_path_visible(j.get("params", {}))
            elif "type" in j and j["type"] == "selection_to_path":
                return self._selection_to_path(j.get("params", {}))
            elif "type" in j and j["type"] == "export_path_as_svg":
                return self._export_path_as_svg(j.get("params", {}))
            elif "type" in j and j["type"] == "add_text_on_path":
                return self._add_text_on_path(j.get("params", {}))
            elif "type" in j and j["type"] == "text_layer_to_path":
                return self._text_layer_to_path(j.get("params", {}))
            # ── Category 14: Non-Destructive Filters ──────────────────────────
            elif "type" in j and j["type"] == "apply_filter_nondestructive":
                return self._apply_filter_nondestructive(j.get("params", {}))
            elif "type" in j and j["type"] == "list_layer_filters":
                return self._list_layer_filters(j.get("params", {}))
            elif "type" in j and j["type"] == "update_layer_filter":
                return self._update_layer_filter(j.get("params", {}))
            elif "type" in j and j["type"] == "remove_layer_filter":
                return self._remove_layer_filter(j.get("params", {}))
            elif "type" in j and j["type"] == "toggle_layer_filter":
                return self._toggle_layer_filter(j.get("params", {}))
            elif "type" in j and j["type"] == "reorder_layer_filter":
                return self._reorder_layer_filter(j.get("params", {}))
            elif "type" in j and j["type"] == "merge_layer_filter":
                return self._merge_layer_filter(j.get("params", {}))
            # ── Category 13: Channels & Masks ─────────────────────────────────
            elif "type" in j and j["type"] == "list_channels":
                return self._list_channels(j.get("params", {}))
            elif "type" in j and j["type"] == "save_selection_as_channel":
                return self._save_selection_as_channel(j.get("params", {}))
            elif "type" in j and j["type"] == "channel_to_selection":
                return self._channel_to_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "duplicate_channel":
                return self._duplicate_channel(j.get("params", {}))
            elif "type" in j and j["type"] == "delete_channel":
                return self._delete_channel(j.get("params", {}))
            elif "type" in j and j["type"] == "rename_channel":
                return self._rename_channel(j.get("params", {}))
            elif "type" in j and j["type"] == "set_channel_properties":
                return self._set_channel_properties(j.get("params", {}))
            elif "type" in j and j["type"] == "quick_mask_toggle":
                return self._quick_mask_toggle(j.get("params", {}))
            elif "type" in j and j["type"] == "layer_mask_to_selection":
                return self._layer_mask_to_selection(j.get("params", {}))
            elif "type" in j and j["type"] == "invert_layer_mask":
                return self._invert_layer_mask(j.get("params", {}))
            elif "cmds" in j:
                a = ['python-fu-exec', j["cmds"]]
            else:
                p = j["params"]
                a = p['args']

            # Protect against empty args list
            if len(a) == 0:
                return {
                    "status": "error",
                    "error": "No command arguments provided"
                }

            # Auto-join indented-continuation lines back into their block.
            # Fixes the long-standing quirk where
            #   ["def foo():", "    return 1"]
            # exec'd each entry separately and raised "expected an indented
            # block". Callers that genuinely want per-line exec can opt out
            # by passing params.no_auto_join = True.
            no_auto_join = False
            if "params" in j and isinstance(j["params"], dict):
                no_auto_join = bool(j["params"].get("no_auto_join", False))
            if len(a) > 1 and not no_auto_join:
                a = [a[0], self._normalize_exec_lines(a[1])]

            if a[0] == 'python-fu-eval':
                if len(a) > 0:
                    print(f"evaluating exprs: {a[1]}")
                    vals = [str(eval(e)) for e in a[1]]
                    results = {
                        "status": "success",
                        "results": vals
                    }
                else:
                    results = {
                    "status": "success",
                    "results": "[NULL]"
                }
                print(f"expression result: {results}")
                return results
            else:
                outputs = ["OK"]
                if len(a) > 0:
                    print(f"Executing commands: {a[1]}")
                    outputs = [exec_and_get_results(c, self.context) for c in a[1]]
                else:
                    print("no command to execute")
                result = {
                    "status": "success",
                    "results": outputs
                }

                print(f"Command result: {result}")
                return result

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def _get_current_image_bitmap(self, params=None):
        """Get the current image as a base64-encoded bitmap with optional scaling and region selection."""
        try:
            if params is None:
                params = {}
                
            print(f"Getting current image bitmap with params: {params}")

            # Extract parameters
            max_width = params.get("max_width")
            max_height = params.get("max_height")
            
            # Extract region parameters if provided
            region = params.get("region", {})
            
            # Validate region parameters if provided
            if region:
                # Validate region parameter types
                for key, expected_type in [("origin_x", int), ("origin_y", int), 
                                         ("width", int), ("height", int),
                                         ("max_width", int), ("max_height", int)]:
                    if key in region and region[key] is not None:
                        if not isinstance(region[key], expected_type):
                            return {
                                "status": "error",
                                "error": f"Region parameter '{key}' must be of type {expected_type.__name__}, got {type(region[key]).__name__}"
                            }
                        if region[key] < 0:
                            return {
                                "status": "error", 
                                "error": f"Region parameter '{key}' must be non-negative, got {region[key]}"
                            }
            
            origin_x = region.get("origin_x")
            origin_y = region.get("origin_y")
            region_width = region.get("width")
            region_height = region.get("height")
            scaled_to_width = region.get("max_width")  # Region scaling uses max_width/max_height
            scaled_to_height = region.get("max_height")

            # Get the current images
            images = Gimp.get_images()
            if not images:
                return {
                    "status": "error",
                    "error": "No images are currently open in GIMP"
                }
            
            # Use the first image (most recently active)
            original_image = images[0]
            
            # Get original image dimensions
            orig_img_width = original_image.get_width()
            orig_img_height = original_image.get_height()
            
            # Determine working image and region
            working_image = None
            should_delete_working = False
            
            # Case 1: Region selection
            if any(param is not None for param in [origin_x, origin_y, region_width, region_height]):
                print("Processing region extraction...")
                
                # Validate region parameters
                if origin_x is None or origin_y is None or region_width is None or region_height is None:
                    return {
                        "status": "error",
                        "error": "For region selection, all parameters are required: origin_x, origin_y, width, height"
                    }
                
                # Validate region bounds
                if (origin_x < 0 or origin_y < 0 or 
                    origin_x + region_width > orig_img_width or 
                    origin_y + region_height > orig_img_height):
                    return {
                        "status": "error",
                        "error": f"Region bounds invalid. Image size: {orig_img_width}x{orig_img_height}, "
                               f"requested region: ({origin_x},{origin_y}) {region_width}x{region_height}"
                    }
                
                # Create new image with the region
                working_image = Gimp.Image.new(region_width, region_height, original_image.get_base_type())
                should_delete_working = True
                
                # Copy the region from original image
                # First, select the region in the original image
                original_image.select_rectangle(Gimp.ChannelOps.REPLACE, origin_x, origin_y, region_width, region_height)
                
                # Get the active layer from original image
                orig_layers = original_image.get_layers()
                if not orig_layers:
                    return {
                        "status": "error",
                        "error": "No layers found in original image"
                    }
                
                # Create a new layer in working image
                # In GIMP 3.0+, use the image's base type instead of layer.get_image_type()
                try:
                    # Try to get layer type - fallback to image base type
                    if hasattr(orig_layers[0], 'get_type'):
                        layer_type = orig_layers[0].get_type()
                    else:
                        # Use image base type as fallback
                        layer_type = original_image.get_base_type()
                except AttributeError:
                    # Final fallback - use RGB
                    layer_type = Gimp.ImageBaseType.RGB
                
                new_layer = Gimp.Layer.new(working_image, 'Region', region_width, region_height, 
                                         layer_type, 100, Gimp.LayerMode.NORMAL)
                working_image.insert_layer(new_layer, None, 0)
                
                # Copy and paste the selection
                Gimp.edit_copy([orig_layers[0]])
                floating_sel = Gimp.edit_paste(new_layer, True)[0]
                Gimp.floating_sel_anchor(floating_sel)
                
                # Clear selection
                try:
                    # Try different methods to clear selection based on GIMP version
                    if hasattr(original_image, 'select_none'):
                        original_image.select_none()
                    else:
                        # Use Gimp.Selection.none() for GIMP 3.0+
                        Gimp.Selection.none(original_image)
                except (AttributeError, RuntimeError) as e:
                    print(f"Warning: Could not clear selection: {e}")
                
            else:
                # Case 2: Full image
                print("Processing full image...")
                working_image = original_image
                should_delete_working = False
            
            # Now handle scaling if needed
            final_image = working_image
            should_delete_final = should_delete_working
            
            # Calculate target dimensions
            current_width = working_image.get_width()
            current_height = working_image.get_height()
            target_width = current_width
            target_height = current_height
            
            # Determine scaling target
            if scaled_to_width is not None and scaled_to_height is not None:
                # Region scaling - use scaled_to dimensions
                max_w, max_h = scaled_to_width, scaled_to_height
            elif max_width is not None and max_height is not None:
                # Full image scaling - use max dimensions
                max_w, max_h = max_width, max_height
            else:
                max_w = max_h = None
            
            # Apply center inside scaling if target dimensions provided
            if max_w is not None and max_h is not None:
                # Calculate center inside scaling
                aspect_ratio = current_width / current_height
                max_aspect_ratio = max_w / max_h
                
                if aspect_ratio > max_aspect_ratio:
                    # Width is the limiting factor
                    target_width = max_w
                    target_height = int(max_w / aspect_ratio)
                else:
                    # Height is the limiting factor
                    target_height = max_h
                    target_width = int(max_h * aspect_ratio)
                
                print(f"Scaling from {current_width}x{current_height} to {target_width}x{target_height}")
                
                # Scale the image if dimensions changed
                if target_width != current_width or target_height != current_height:
                    # Create scaled image
                    final_image = working_image.duplicate()
                    should_delete_final = True
                    
                    # Scale the image with timeout consideration for large operations
                    scaling_ratio = (target_width * target_height) / (current_width * current_height)
                    if scaling_ratio > LARGE_SCALING_THRESHOLD:  # Scaling up significantly
                        print(f"Warning: Large scaling operation detected (ratio: {scaling_ratio:.2f}). This may take time.")
                    
                    try:
                        final_image.scale(target_width, target_height)
                    except (RuntimeError) as scale_error:
                        # Clean up and return error for scaling failures
                        if should_delete_final:
                            try:
                                final_image.delete()
                            except (AttributeError, RuntimeError):
                                pass
                        raise RuntimeError(f"Failed to scale image from {current_width}x{current_height} to {target_width}x{target_height}: {scale_error}")
        
            # Create a temporary file for export
            temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(temp_fd)  # Close the file descriptor as GIMP will handle the file
            
            try:
                # Export the final image as PNG
                # Get all layers - we'll export the flattened image
                layers = final_image.get_layers()
                if not layers:
                    return {
                        "status": "error", 
                        "error": "No layers found in the processed image"
                    }
                
                # For PNG export, we can use all layers or the active layer
                try:
                    drawable = (final_image.get_selected_layers() or final_image.get_layers() or [None])[0]
                except (AttributeError, RuntimeError):
                    # If get_active_layer doesn't exist or fails, use the first layer
                    drawable = layers[0]
                
                if not drawable:
                    drawable = layers[0]
                
                # Export the image to PNG
                try:
                    # In GIMP 3.0, use the simplified export approach
                    from gi.repository import Gio
                    file_obj = Gio.File.new_for_path(temp_path)
                    
                    # Use file-png-export with the correct parameters for GIMP 3.0
                    export_proc = Gimp.get_pdb().lookup_procedure('file-png-export')
                    if not export_proc:
                        return {
                            "status": "error",
                            "error": "PNG export procedure not found"
                        }
                    
                    export_config = export_proc.create_config()
                    export_config.set_property('image', final_image)
                    export_config.set_property('file', file_obj)
                    # Try different property names that might exist
                    try:
                        export_config.set_property('drawable', drawable)
                    except Exception:
                        try:
                            export_config.set_property('drawables', [drawable])
                        except Exception:
                            # Some export procedures might not need drawable specification
                            pass
                    
                    result = export_proc.run(export_config)
                    print(f"Export result: {result}")
                    
                except Exception as export_error:
                    print(f"Export error: {export_error}")
                    # Fallback: try using the PDB directly with correct arguments
                    try:
                        from gi.repository import Gio
                        file_obj = Gio.File.new_for_path(temp_path)
                        
                        # Try alternative approach using Gimp.file_save with correct number of arguments
                        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, final_image, file_obj)
                        print("Fallback export successful")
                    except Exception as fallback_error:
                        print(f"Fallback export error: {fallback_error}")
                        # Try another fallback using gimp-file-save PDB procedure
                        try:
                            pdb = Gimp.get_pdb()
                            save_proc = pdb.lookup_procedure('gimp-file-save')
                            if save_proc:
                                save_config = save_proc.create_config()
                                save_config.set_property('image', final_image)
                                save_config.set_property('file', file_obj)
                                save_result = save_proc.run(save_config)
                                print(f"PDB save result: {save_result}")
                            else:
                                return {
                                    "status": "error",
                                    "error": f"All export methods failed: {export_error}, fallback: {fallback_error}"
                                }
                        except Exception as pdb_error:
                            return {
                                "status": "error",
                                "error": f"All export methods failed: {export_error}, fallback: {fallback_error}, PDB: {pdb_error}"
                            }
                
                # Read the exported file and encode as base64
                with open(temp_path, 'rb') as f:
                    image_data = f.read()
                    encoded_image = base64.b64encode(image_data).decode('utf-8')
                
                # Get final image metadata
                final_width = final_image.get_width()
                final_height = final_image.get_height()
                
                return {
                    "status": "success",
                    "results": {
                        "image_data": encoded_image,
                        "format": "png",
                        "width": final_width,
                        "height": final_height,
                        "original_width": orig_img_width,
                        "original_height": orig_img_height,
                        "encoding": "base64",
                        "processing_applied": {
                            "region_extracted": any(param is not None for param in [origin_x, origin_y, region_width, region_height]),
                            "scaled": target_width != current_width or target_height != current_height,
                            "region_coords": {"x": origin_x, "y": origin_y, "w": region_width, "h": region_height} if origin_x is not None else None
                        }
                    }
                }
                
            finally:
                # Clean up temporary images
                if should_delete_final and final_image != working_image:
                    try:
                        final_image.delete()
                    except (AttributeError, RuntimeError) as e:
                        print(f"Warning: Failed to delete final temporary image: {e}")
                if should_delete_working and working_image != original_image:
                    try:
                        working_image.delete()
                    except (AttributeError, RuntimeError) as e:
                        print(f"Warning: Failed to delete working temporary image: {e}")
                        
                # Clean up the temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except (RuntimeError, AttributeError, OSError, ValueError) as e:
            return {
                "status": "error",
                "error": f"Processing error: {str(e)}",
                "traceback": traceback.format_exc()
            }

    def _get_current_image_metadata(self):
        """Get comprehensive metadata about the current image without bitmap data."""
        try:
            print("Getting current image metadata...")
            
            # Get the current images
            images = Gimp.get_images()
            if not images:
                return {
                    "status": "error",
                    "error": "No images are currently open in GIMP"
                }
            
            # Use the first image (most recently active)
            image = images[0]
            
            # Basic image properties
            width = image.get_width()
            height = image.get_height()
            
            # Get image type and base type
            base_type = image.get_base_type()
            base_type_str = self._base_type_to_string(base_type)
            
            # Get precision and color profile info
            precision = image.get_precision()
            precision_str = self._precision_to_string(precision)
            
            # Get layers information
            layers = image.get_layers()
            layers_info = []
            for i, layer in enumerate(layers):
                try:
                    layer_info = {
                        "name": layer.get_name(),
                        "visible": layer.get_visible(),
                        "opacity": layer.get_opacity(),
                        "width": layer.get_width(),
                        "height": layer.get_height(),
                        "has_alpha": layer.has_alpha(),
                        "is_group": hasattr(layer, 'get_children') and callable(getattr(layer, 'get_children')),
                        "layer_type": self._get_layer_type_string(layer)
                    }
                    # Try to get layer mode if available
                    try:
                        layer_info["blend_mode"] = str(layer.get_mode())
                    except Exception:
                        layer_info["blend_mode"] = "unknown"
                    
                    layers_info.append(layer_info)
                except Exception as layer_error:
                    print(f"Error getting layer {i} info: {layer_error}")
                    layers_info.append({
                        "name": f"Layer {i}",
                        "error": str(layer_error)
                    })
            
            # Get channels information
            channels = image.get_channels()
            channels_info = []
            for i, channel in enumerate(channels):
                try:
                    channel_info = {
                        "name": channel.get_name(),
                        "visible": channel.get_visible(),
                        "opacity": channel.get_opacity(),
                        "color": str(channel.get_color()) if hasattr(channel, 'get_color') else "unknown"
                    }
                    channels_info.append(channel_info)
                except Exception as channel_error:
                    print(f"Error getting channel {i} info: {channel_error}")
                    channels_info.append({
                        "name": f"Channel {i}",
                        "error": str(channel_error)
                    })
            
            # Get paths/vectors information
            paths = []
            try:
                image_paths = image.get_paths()
                for i, path in enumerate(image_paths):
                    try:
                        path_info = {
                            "name": path.get_name(),
                            "visible": path.get_visible(),
                            "num_strokes": len(path.get_strokes()) if hasattr(path, 'get_strokes') else 0
                        }
                        paths.append(path_info)
                    except Exception as path_error:
                        print(f"Error getting path {i} info: {path_error}")
                        paths.append({
                            "name": f"Path {i}",
                            "error": str(path_error)
                        })
            except Exception as paths_error:
                print(f"Error getting paths: {paths_error}")
            
            # Get file information if available
            file_info = {}
            try:
                image_file = image.get_file()
                if image_file:
                    file_info = {
                        "path": image_file.get_path() if hasattr(image_file, 'get_path') else None,
                        "uri": image_file.get_uri() if hasattr(image_file, 'get_uri') else None,
                        "basename": image_file.get_basename() if hasattr(image_file, 'get_basename') else None
                    }
            except Exception as file_error:
                print(f"Error getting file info: {file_error}")
                file_info = {"error": str(file_error)}
            
            # Get resolution information
            resolution_x = resolution_y = None
            try:
                resolution_x, resolution_y = image.get_resolution()
            except Exception as res_error:
                print(f"Error getting resolution: {res_error}")
            
            # Check if image has unsaved changes
            is_dirty = False
            try:
                is_dirty = image.is_dirty()
            except Exception as dirty_error:
                print(f"Error getting dirty status: {dirty_error}")
            
            metadata = {
                "basic": {
                    "width": width,
                    "height": height,
                    "base_type": base_type_str,
                    "precision": precision_str,
                    "resolution_x": resolution_x,
                    "resolution_y": resolution_y,
                    "is_dirty": is_dirty
                },
                "structure": {
                    "num_layers": len(layers),
                    "num_channels": len(channels),
                    "num_paths": len(paths),
                    "layers": layers_info,
                    "channels": channels_info,
                    "paths": paths
                },
                "file": file_info
            }
            
            return {
                "status": "success",
                "results": metadata
            }
            
        except Exception as e:
            error_msg = f"Error getting image metadata: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def _base_type_to_string(self, base_type):
        """Convert GIMP base type enum to string."""
        try:
            base_type_map = {
                Gimp.ImageBaseType.RGB: "RGB",
                Gimp.ImageBaseType.GRAY: "Grayscale",
                Gimp.ImageBaseType.INDEXED: "Indexed"
            }
            return base_type_map.get(base_type, f"Unknown ({base_type})")
        except Exception:
            return str(base_type)

    def _precision_to_string(self, precision):
        """Convert GIMP precision enum to readable string."""
        try:
            precision_map = {
                100: "u8",      # Gimp.Precision.U8_LINEAR
                150: "u8-gamma", # Gimp.Precision.U8_GAMMA  
                200: "u16",     # Gimp.Precision.U16_LINEAR
                250: "u16-gamma", # Gimp.Precision.U16_GAMMA
                300: "u32",     # Gimp.Precision.U32_LINEAR
                350: "u32-gamma", # Gimp.Precision.U32_GAMMA
                500: "half",    # Gimp.Precision.HALF_LINEAR
                550: "half-gamma", # Gimp.Precision.HALF_GAMMA
                600: "float",   # Gimp.Precision.FLOAT_LINEAR
                650: "float-gamma", # Gimp.Precision.FLOAT_GAMMA
                700: "double",  # Gimp.Precision.DOUBLE_LINEAR
                750: "double-gamma" # Gimp.Precision.DOUBLE_GAMMA
            }
            return precision_map.get(int(precision), f"precision-{precision}")
        except Exception:
            return str(precision)
            
    def _get_layer_type_string(self, layer):
        """Get layer type string with compatibility for different GIMP versions."""
        try:
            # Try different methods to get layer type
            if hasattr(layer, 'get_type'):
                return str(layer.get_type())
            elif hasattr(layer, 'get_image_type'):
                return str(layer.get_image_type())
            elif hasattr(layer, 'type'):
                return str(layer.type)
            else:
                # Fallback - determine from layer properties
                if layer.has_alpha():
                    return "RGBA"
                else:
                    return "RGB"
        except Exception as e:
            print(f"Warning: Could not determine layer type: {e}")
            return "unknown"

    def _get_gimp_info(self):
        """Get comprehensive information about GIMP installation and environment."""
        try:
            print("Getting GIMP environment information...")
            
            gimp_info = {}
            
            # Basic GIMP version and build information
            try:
                version_info = {}
                
                # Try different methods to get version info
                try:
                    # Try the version() method if it exists
                    if hasattr(Gimp, 'version'):
                        version_info["version_method"] = str(Gimp.version())
                except Exception as v_error:
                    version_info["version_method_error"] = str(v_error)
                
                # Try to get version from constants if they exist
                for attr in ['MAJOR_VERSION', 'MINOR_VERSION', 'MICRO_VERSION']:
                    try:
                        if hasattr(Gimp, attr):
                            version_info[attr.lower()] = getattr(Gimp, attr)
                    except Exception as attr_error:
                        version_info[f"{attr.lower()}_error"] = str(attr_error)
                
                # Get available version-related attributes
                version_attrs = [attr for attr in dir(Gimp) if 'version' in attr.lower()]
                if version_attrs:
                    version_info["available_version_attributes"] = version_attrs
                
                # Try to get version string from any available source
                version_string = "Unknown"
                try:
                    # Check if there's a version string constant
                    if hasattr(Gimp, 'VERSION'):
                        version_string = str(Gimp.VERSION)
                    elif hasattr(Gimp, 'version_string'):
                        version_string = str(Gimp.version_string())
                    elif hasattr(Gimp, 'get_version'):
                        version_string = str(Gimp.get_version())
                except Exception:
                    pass
                
                version_info["detected_version"] = version_string
                version_info["gimp_module_type"] = str(type(Gimp))
                
                gimp_info["version"] = version_info
                
            except Exception as version_error:
                print(f"Error getting version info: {version_error}")
                gimp_info["version"] = {"error": str(version_error)}
            
            # Installation and directory information
            try:
                directories = {}
                
                # Safely try each directory method
                directory_methods = [
                    ('user_directory', 'directory'),
                    ('system_data_directory', 'data_directory'), 
                    ('locale_directory', 'locale_directory'),
                    ('plugin_directory', 'plug_in_directory'),
                    ('sysconf_directory', 'sysconf_directory')
                ]
                
                for dir_name, method_name in directory_methods:
                    try:
                        if hasattr(Gimp, method_name):
                            method = getattr(Gimp, method_name)
                            if callable(method):
                                directories[dir_name] = str(method())
                            else:
                                directories[dir_name] = str(method)
                        else:
                            directories[f"{dir_name}_not_available"] = True
                    except Exception as method_error:
                        directories[f"{dir_name}_error"] = str(method_error)
                
                # List available directory-related methods
                dir_attrs = [attr for attr in dir(Gimp) if 'dir' in attr.lower()]
                directories["available_directory_methods"] = dir_attrs
                
                gimp_info["directories"] = directories
                
            except Exception as dir_error:
                print(f"Error getting directory info: {dir_error}")
                gimp_info["directories"] = {"error": str(dir_error)}
            
            # Current session information
            try:
                images = Gimp.get_images()
                gimp_info["session"] = {
                    "num_open_images": len(images),
                    "has_open_images": len(images) > 0,
                    "open_image_files": []
                }
                
                # Get file information for open images
                for i, image in enumerate(images):
                    try:
                        image_file = image.get_file()
                        file_info = {
                            "index": i,
                            "width": image.get_width(),
                            "height": image.get_height(),
                            "base_type": self._base_type_to_string(image.get_base_type()),
                            "is_dirty": image.is_dirty() if hasattr(image, 'is_dirty') else None
                        }
                        
                        if image_file:
                            file_info.update({
                                "path": image_file.get_path() if hasattr(image_file, 'get_path') else None,
                                "basename": image_file.get_basename() if hasattr(image_file, 'get_basename') else None
                            })
                        else:
                            file_info["path"] = "Untitled"
                            
                        gimp_info["session"]["open_image_files"].append(file_info)
                    except Exception as image_error:
                        print(f"Error getting image {i} info: {image_error}")
                        gimp_info["session"]["open_image_files"].append({
                            "index": i,
                            "error": str(image_error)
                        })
                        
            except Exception as session_error:
                print(f"Error getting session info: {session_error}")
                gimp_info["session"] = {"error": str(session_error)}
            
            # PDB (Procedure Database) information
            try:
                pdb = Gimp.get_pdb()
                pdb_info = {
                    "available": pdb is not None,
                    "type": str(type(pdb)) if pdb else None
                }
                
                # Try to get some example procedures
                if pdb:
                    sample_procedures = []
                    try:
                        # Test some common procedures
                        test_procs = ['file-png-export', 'gimp-file-save', 'gimp-image-new', 'python-fu-console']
                        for proc_name in test_procs:
                            try:
                                proc = pdb.lookup_procedure(proc_name)
                                sample_procedures.append({
                                    "name": proc_name,
                                    "available": proc is not None,
                                    "type": str(type(proc)) if proc else None
                                })
                            except Exception:
                                sample_procedures.append({
                                    "name": proc_name,
                                    "available": False,
                                    "error": "lookup_failed"
                                })
                    except Exception as proc_error:
                        print(f"Error testing procedures: {proc_error}")
                    
                    pdb_info["sample_procedures"] = sample_procedures
                
                gimp_info["pdb"] = pdb_info
                
            except Exception as pdb_error:
                print(f"Error getting PDB info: {pdb_error}")
                gimp_info["pdb"] = {"error": str(pdb_error)}
            
            # Context and environment information
            try:
                context_info = {}
                
                # Try to get current context information
                try:
                    fg_color = Gimp.context_get_foreground()
                    context_info["foreground_color"] = str(fg_color) if fg_color else None
                except Exception:
                    context_info["foreground_color"] = "unavailable"
                
                try:
                    bg_color = Gimp.context_get_background()
                    context_info["background_color"] = str(bg_color) if bg_color else None
                except Exception:
                    context_info["background_color"] = "unavailable"
                
                try:
                    brush_size = Gimp.context_get_brush_size()
                    context_info["brush_size"] = brush_size if brush_size else None
                except Exception:
                    context_info["brush_size"] = "unavailable"
                
                gimp_info["context"] = context_info
                
            except Exception as context_error:
                print(f"Error getting context info: {context_error}")
                gimp_info["context"] = {"error": str(context_error)}
            
            # Capabilities and features
            try:
                capabilities = {
                    "has_python_console": True,  # We're running Python
                    "mcp_server_running": True,  # We're responding to MCP requests
                    "supports_image_export": True,  # We have the bitmap export function
                    "supports_metadata_export": True,  # We have the metadata function
                    "supports_gimp_info": True,  # We have the gimp info function
                    "api_version": "3.0+",
                    "python_version": sys.version,
                    "available_modules": [],
                    "gimp_module_attributes": len(dir(Gimp)),
                    "gimp_methods": [attr for attr in dir(Gimp) if callable(getattr(Gimp, attr, None))][:20]  # First 20 methods
                }
                
                # Test for available Python modules
                test_modules = ['gi.repository.Gimp', 'gi.repository.Gegl', 'gi.repository.Gio', 'json', 'base64', 'tempfile']
                for module_name in test_modules:
                    try:
                        if module_name == 'gi.repository.Gimp':
                            # Already imported
                            capabilities["available_modules"].append({"name": module_name, "available": True})
                        elif module_name == 'gi.repository.Gegl':
                            from gi.repository import Gegl  # noqa: F401
                            capabilities["available_modules"].append({"name": module_name, "available": True})
                        elif module_name == 'gi.repository.Gio':
                            from gi.repository import Gio  # noqa: F401
                            capabilities["available_modules"].append({"name": module_name, "available": True})
                        else:
                            __import__(module_name)
                            capabilities["available_modules"].append({"name": module_name, "available": True})
                    except ImportError:
                        capabilities["available_modules"].append({"name": module_name, "available": False})
                    except Exception as mod_error:
                        capabilities["available_modules"].append({"name": module_name, "available": False, "error": str(mod_error)})
                
                gimp_info["capabilities"] = capabilities
                
            except Exception as cap_error:
                print(f"Error getting capabilities: {cap_error}")
                gimp_info["capabilities"] = {"error": str(cap_error)}
            
            # System and platform information
            try:
                
                system_info = {
                    "platform": platform.platform(),
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python_version": platform.python_version(),
                    "environment_vars": {
                        "HOME": os.environ.get("HOME"),
                        "USER": os.environ.get("USER"), 
                        "GIMP_PLUG_IN_DIR": os.environ.get("GIMP_PLUG_IN_DIR"),
                        "GIMP_DATA_DIR": os.environ.get("GIMP_DATA_DIR")
                    }
                }
                
                gimp_info["system"] = system_info
                
            except Exception as sys_error:
                print(f"Error getting system info: {sys_error}")
                gimp_info["system"] = {"error": str(sys_error)}
            
            return {
                "status": "success",
                "results": gimp_info
            }
            
        except Exception as e:
            error_msg = f"Error getting GIMP info: {str(e)}\n{traceback.format_exc()}"
            return {
                "status": "error",
                "error": error_msg,
                "traceback": traceback.format_exc()
            }

    def _get_context_state(self):
        """Get current GIMP context state (colors, brush, tool settings)."""
        try:
            print("Getting GIMP context state...")

            context_state = {}

            # Get foreground and background colors
            try:
                fg_color = Gimp.context_get_foreground()
                bg_color = Gimp.context_get_background()

                # Convert colors to RGB values
                context_state["foreground_color"] = {
                    "color_object": str(fg_color),
                    "description": "Current foreground color"
                }
                context_state["background_color"] = {
                    "color_object": str(bg_color),
                    "description": "Current background color"
                }

                # Try to get RGB values if possible
                try:
                    if hasattr(fg_color, 'get_rgba'):
                        rgba = fg_color.get_rgba()
                        context_state["foreground_color"]["rgba"] = list(rgba) if rgba else None
                except Exception as color_error:
                    context_state["foreground_color"]["rgba_error"] = str(color_error)

                try:
                    if hasattr(bg_color, 'get_rgba'):
                        rgba = bg_color.get_rgba()
                        context_state["background_color"]["rgba"] = list(rgba) if rgba else None
                except Exception as color_error:
                    context_state["background_color"]["rgba_error"] = str(color_error)

            except Exception as color_err:
                context_state["colors_error"] = str(color_err)

            # Get brush information
            try:
                brush = Gimp.context_get_brush()
                if brush:
                    context_state["brush"] = {
                        "name": brush.get_name() if hasattr(brush, 'get_name') else str(brush),
                        "description": "Current brush"
                    }
            except Exception as brush_err:
                context_state["brush_error"] = str(brush_err)

            # Get opacity
            try:
                opacity = Gimp.context_get_opacity()
                context_state["opacity"] = {
                    "value": opacity,  # Already in percentage (0-100)
                    "description": "Current opacity percentage (0-100)"
                }
            except Exception as opacity_err:
                context_state["opacity_error"] = str(opacity_err)

            # Get paint mode
            try:
                paint_mode = Gimp.context_get_paint_mode()
                context_state["paint_mode"] = {
                    "value": str(paint_mode),
                    "description": "Current paint/blend mode"
                }
            except Exception as mode_err:
                context_state["paint_mode_error"] = str(mode_err)

            # Get feather setting (if available)
            try:
                feather = Gimp.context_get_feather()
                feather_radius = Gimp.context_get_feather_radius()
                context_state["feather"] = {
                    "enabled": feather,
                    "radius": feather_radius,
                    "description": "Selection feathering state"
                }
            except Exception:
                context_state["feather_note"] = "Feather settings not available in context"

            # Get antialias setting
            try:
                antialias = Gimp.context_get_antialias()
                context_state["antialias"] = {
                    "enabled": antialias,
                    "description": "Antialiasing state for selections"
                }
            except Exception:
                context_state["antialias_note"] = "Antialias setting not available"

            return {
                "status": "success",
                "results": context_state
            }

        except Exception as e:
            error_msg = f"Error getting context state: {str(e)}\n{traceback.format_exc()}"
            return {
                "status": "error",
                "error": error_msg,
                "traceback": traceback.format_exc()
            }

    def _restart_server(self):
        """Gracefully restart the MCP socket server in-place."""
        try:
            print("Restarting MCP server socket...")
            # Close existing socket to force reconnect on next client call
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None

            # Re-bind a fresh socket
            import time
            time.sleep(0.3)
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.settimeout(1.0)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            print(f"MCP server restarted on {self.host}:{self.port}")
            return {
                "status": "success",
                "results": {"restarted": True, "host": self.host, "port": self.port}
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Restart failed: {str(e)}",
                "traceback": traceback.format_exc()
            }

    def _new_canvas(self, params):
        """Create a new blank canvas and open it in a GIMP display window."""
        try:
            width  = int(params.get("width", 1024))
            height = int(params.get("height", 1024))
            name   = str(params.get("name", "Untitled"))
            color_mode = str(params.get("color_mode", "RGB")).upper()
            fill   = str(params.get("fill", "white"))
            resolution = int(params.get("resolution", 72))

            mode_map = {
                "RGB":   Gimp.ImageBaseType.RGB,
                "RGBA":  Gimp.ImageBaseType.RGB,
                "GRAY":  Gimp.ImageBaseType.GRAY,
                "GRAYA": Gimp.ImageBaseType.GRAY,
            }
            layer_type_map = {
                "RGB":   Gimp.ImageType.RGB_IMAGE,
                "RGBA":  Gimp.ImageType.RGBA_IMAGE,
                "GRAY":  Gimp.ImageType.GRAY_IMAGE,
                "GRAYA": Gimp.ImageType.GRAYA_IMAGE,
            }
            base_type  = mode_map.get(color_mode, Gimp.ImageBaseType.RGB)
            layer_type = layer_type_map.get(color_mode, Gimp.ImageType.RGB_IMAGE)

            from gi.repository import Gegl
            image = Gimp.Image.new(width, height, base_type)
            image.set_resolution(resolution, resolution)

            layer = Gimp.Layer.new(image, name, width, height, layer_type, 100, Gimp.LayerMode.NORMAL)
            image.insert_layer(layer, None, 0)

            if fill.lower() == "transparent":
                layer.add_alpha()
                Gimp.Drawable.edit_fill(layer, Gimp.FillType.TRANSPARENT)
            else:
                bg_color = Gegl.Color.new(fill)
                Gimp.context_set_background(bg_color)
                Gimp.Drawable.edit_fill(layer, Gimp.FillType.BACKGROUND)

            Gimp.Display.new(image)
            Gimp.displays_flush()

            print(f"New canvas created: {width}x{height} {color_mode} fill={fill}")
            return {
                "status": "success",
                "results": {
                    "image_id": image.get_id(),
                    "width": width,
                    "height": height,
                    "color_mode": color_mode,
                    "fill": fill,
                    "resolution": resolution,
                    "display_opened": True
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"new_canvas failed: {str(e)}",
                "traceback": traceback.format_exc()
            }


    # =========================================================================
    # SHARED HELPERS
    # =========================================================================

    def _get_image(self, image_index):
        """Return the image at image_index from Gimp.get_images(), raise if none open."""
        images = Gimp.get_images()
        if not images:
            raise RuntimeError("No images are currently open in GIMP")
        if image_index >= len(images):
            raise RuntimeError(f"image_index {image_index} out of range (only {len(images)} images open)")
        return images[image_index]

    def _resolve_layer(self, image, layer_name, layer_index):
        """Resolve a layer by name, index, or fall back to the active layer."""
        if layer_name is not None:
            layers = image.get_layers()
            for layer in layers:
                if layer.get_name() == layer_name:
                    return layer
            raise RuntimeError(f"Layer '{layer_name}' not found")
        if layer_index is not None:
            layers = image.get_layers()
            if layer_index >= len(layers):
                raise RuntimeError(f"layer_index {layer_index} out of range")
            return layers[layer_index]
        layer = (image.get_selected_layers() or image.get_layers() or [None])[0]
        if layer is None:
            layers = image.get_layers()
            if not layers:
                raise RuntimeError("No layers in image")
            return layers[0]
        return layer

    def _channel_ops_from_string(self, op):
        """Map operation string to Gimp.ChannelOps enum value."""
        return {
            "replace":   Gimp.ChannelOps.REPLACE,
            "add":       Gimp.ChannelOps.ADD,
            "subtract":  Gimp.ChannelOps.SUBTRACT,
            "intersect": Gimp.ChannelOps.INTERSECT,
        }.get(op.lower(), Gimp.ChannelOps.REPLACE)

    def _interp_from_string(self, interp):
        """Map interpolation string to Gimp.InterpolationType."""
        return {
            "cubic":  Gimp.InterpolationType.CUBIC,
            "linear": Gimp.InterpolationType.LINEAR,
            "none":   Gimp.InterpolationType.NONE,
        }.get(interp.lower(), Gimp.InterpolationType.CUBIC)

    def _export_to_path(self, image, file_path, fmt, quality, flatten, extra_props=None):
        """Export image to file_path in the given format. Returns file size in bytes.

        extra_props, when provided, is a dict of format-specific property
        overrides (e.g. {"compression": 7} for PNG, {"sub-sampling": 2} for
        JPEG). Unknown properties are silently ignored per existing behavior.
        """
        from gi.repository import Gio
        if flatten:
            image = image.duplicate()
            image.flatten()
            should_delete = True
        else:
            should_delete = False
        try:
            gio_file = Gio.File.new_for_path(file_path)
            pdb = Gimp.get_pdb()
            fmt_lower = fmt.lower()
            # GIMP 3.2 renamed the file-*-save procedures to file-*-export.
            # Probe the 3.2 name first, then fall back to the 3.0-era name so
            # this keeps working on older installs.
            EXPORT_PROC_CANDIDATES = {
                "png":  ["file-png-export",  "file-png-save"],
                "jpeg": ["file-jpeg-export", "file-jpeg-save"],
                "jpg":  ["file-jpeg-export", "file-jpeg-save"],
                "webp": ["file-webp-export", "file-webp-save"],
                "tiff": ["file-tiff-export", "file-tiff-save"],
            }
            candidates = EXPORT_PROC_CANDIDATES.get(fmt_lower, ["file-png-export", "file-png-save"])
            proc = None
            for cand in candidates:
                proc = pdb.lookup_procedure(cand)
                if proc is not None:
                    break
            if proc is None:
                Gimp.file_overwrite(Gimp.RunMode.NONINTERACTIVE, image, gio_file)
            else:
                cfg = proc.create_config()
                cfg.set_property("image", image)
                cfg.set_property("file", gio_file)
                try:
                    layers = image.get_layers()
                    drawable = (image.get_selected_layers() or layers or [None])[0]
                    try:
                        cfg.set_property("drawable", drawable)
                    except Exception:
                        pass
                    if fmt_lower in ("jpeg", "jpg"):
                        try:
                            cfg.set_property("quality", quality / 100.0)
                        except Exception:
                            pass
                    if fmt_lower == "webp":
                        try:
                            cfg.set_property("quality", float(quality))
                        except Exception:
                            pass
                    if extra_props:
                        for k, v in extra_props.items():
                            try:
                                cfg.set_property(k, v)
                            except Exception:
                                pass
                except Exception:
                    pass
                proc.run(cfg)
            return os.path.getsize(file_path)
        finally:
            if should_delete:
                try:
                    image.delete()
                except Exception:
                    pass

    def _apply_gegl_filter(self, image, drawable, op_name, props):
        """Apply a GEGL operation to a drawable via gimp-drawable-filter-new."""
        pdb = Gimp.get_pdb()
        # Try the GEGL filter approach via PDB
        filter_proc = pdb.lookup_procedure("gimp-drawable-filter-new")
        if filter_proc:
            cfg = filter_proc.create_config()
            cfg.set_property("drawable", drawable)
            cfg.set_property("operation-name", op_name)
            cfg.set_property("name", op_name)
            result = filter_proc.run(cfg)
            # Get the filter object
            try:
                filtr = result.index(0)
                for k, v in props.items():
                    try:
                        filtr.set_property(k, v)
                    except Exception:
                        pass
                # Apply filter (merge)
                apply_proc = pdb.lookup_procedure("gimp-drawable-merge-filter")
                if apply_proc:
                    acfg = apply_proc.create_config()
                    acfg.set_property("drawable", drawable)
                    acfg.set_property("filter", filtr)
                    apply_proc.run(acfg)
            except Exception:
                pass
        else:
            # Fallback: execute via exec context
            props_code = ", ".join(f'"{k}", {repr(v)}' for k, v in props.items())
            cmds = [
                "from gi.repository import Gimp, Gegl",
                "_img = Gimp.get_images()[0]",
                "_d = (_img.get_selected_layers() or _img.get_layers() or [None])[0]",
                f"_d.apply_drawable_filter_new('{op_name}', '', [{props_code}])",
                "Gimp.displays_flush()",
            ]
            for cmd in cmds:
                exec(cmd, self.context)

    # =========================================================================
    # CATEGORY 1 — File Operations
    # =========================================================================

    def _open_image(self, params):
        """Open an image file, create a display, return metadata."""
        try:
            from gi.repository import Gio
            file_path = params.get("file_path", "")
            gio_file = Gio.File.new_for_path(file_path)
            image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gio_file)
            if image is None:
                return {"status": "error", "error": f"Could not open file: {file_path}"}
            display = Gimp.Display.new(image)
            Gimp.displays_flush()
            base_type = image.get_base_type()
            mode_map = {
                Gimp.ImageBaseType.RGB:     "RGB",
                Gimp.ImageBaseType.GRAY:    "Grayscale",
                Gimp.ImageBaseType.INDEXED: "Indexed",
            }
            return {
                "status": "success",
                "results": {
                    "image_id":      image.get_id(),
                    "width":         image.get_width(),
                    "height":        image.get_height(),
                    "color_mode":    mode_map.get(base_type, str(base_type)),
                    "num_layers":    len(image.get_layers()),
                    "display_opened": display is not None,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _load_image_as_layer(self, params):
        """Import an external image as a new layer in an existing image.

        Uses Gimp.file_load_layer. When fit_canvas is True, the imported
        layer is scaled to fit the target image (preserving aspect ratio)
        and centered.
        """
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            layer_name  = params.get("layer_name")
            fit_canvas  = bool(params.get("fit_canvas", True))

            if not file_path:
                return {"status": "error", "error": "load_image_as_layer: 'file_path' is required"}
            if not os.path.exists(file_path):
                return {"status": "error", "error": f"file not found: {file_path}"}

            image    = self._get_image(image_index)
            gio_file = Gio.File.new_for_path(file_path)
            new_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, gio_file)
            if new_layer is None:
                return {"status": "error", "error": f"could not load as layer: {file_path}"}

            image.undo_group_start()
            try:
                if layer_name:
                    try: new_layer.set_name(layer_name)
                    except Exception: pass
                image.insert_layer(new_layer, None, -1)

                if fit_canvas:
                    img_w, img_h = image.get_width(), image.get_height()
                    lyr_w, lyr_h = new_layer.get_width(), new_layer.get_height()
                    if lyr_w > 0 and lyr_h > 0 and (lyr_w != img_w or lyr_h != img_h):
                        scale = min(img_w / lyr_w, img_h / lyr_h)
                        new_w = max(1, int(lyr_w * scale))
                        new_h = max(1, int(lyr_h * scale))
                        new_layer.scale(new_w, new_h, False)
                        new_layer.translate((img_w - new_w) // 2, (img_h - new_h) // 2)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_id":   new_layer.get_id(),
                "layer_name": new_layer.get_name(),
                "width":      new_layer.get_width(),
                "height":     new_layer.get_height(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _duplicate_image(self, params):
        """Duplicate an image, attach a display, return the new image's index."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            dup   = image.duplicate()
            try:
                Gimp.Display.new(dup)
            except Exception:
                pass
            Gimp.displays_flush()
            images = Gimp.get_images()
            dup_id = dup.get_id()
            new_index = next((i for i, im in enumerate(images) if im.get_id() == dup_id), len(images) - 1)
            return {"status": "success", "results": {
                "status":          "success",
                "new_image_id":    dup_id,
                "new_image_index": new_index,
                "source_image_id": image.get_id(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _save_xcf(self, params):
        """Save image as XCF."""
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path = params.get("file_path", "")
            image = self._get_image(image_index)
            gio_file = Gio.File.new_for_path(file_path)
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-xcf-save")
            if proc:
                cfg = proc.create_config()
                cfg.set_property("image", image)
                cfg.set_property("file", gio_file)
                proc.run(cfg)
            else:
                Gimp.file_overwrite(Gimp.RunMode.NONINTERACTIVE, image, gio_file)
            return {"status": "success", "results": {"status": "success", "file_path": file_path}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_image(self, params):
        """Export image to raster format, optionally with format-specific knobs."""
        try:
            image_index     = int(params.get("image_index", 0))
            file_path       = params.get("file_path", "")
            fmt             = params.get("format", "png")
            quality         = int(params.get("quality", 90))
            flatten         = bool(params.get("flatten", True))
            png_compression = params.get("png_compression")
            jpeg_subsample  = params.get("jpeg_subsample")

            extra_props = {}
            fmt_lower = fmt.lower()
            if fmt_lower == "png" and png_compression is not None:
                extra_props["compression"] = int(png_compression)
            if fmt_lower in ("jpeg", "jpg") and jpeg_subsample is not None:
                extra_props["sub-sampling"] = int(jpeg_subsample)

            image = self._get_image(image_index)
            file_size = self._export_to_path(image, file_path, fmt, quality, flatten,
                                             extra_props or None)
            Gimp.displays_flush()
            return {
                "status": "success",
                "results": {
                    "status":          "success",
                    "file_path":       file_path,
                    "format":          fmt,
                    "file_size_bytes": file_size,
                    "extra_props":     extra_props,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _batch_export(self, params):
        """Export all (or one) open images to output_dir."""
        try:
            output_dir   = params.get("output_dir", "")
            fmt          = params.get("format", "png")
            quality      = int(params.get("quality", 90))
            name_pattern = params.get("name_pattern", "{name}")
            image_index  = params.get("image_index", None)

            images = Gimp.get_images()
            if not images:
                return {"status": "error", "error": "No images open"}

            targets = [(i, img) for i, img in enumerate(images)]
            if image_index is not None:
                targets = [(image_index, images[int(image_index)])]

            os.makedirs(output_dir, exist_ok=True)
            exported = []
            errors = []

            for idx, image in targets:
                try:
                    gio_file = image.get_file()
                    raw_name = gio_file.get_basename().rsplit(".", 1)[0] if gio_file else f"image_{idx}"
                    filename = name_pattern.format(name=raw_name, index=idx) + f".{fmt}"
                    out_path = os.path.join(output_dir, filename)
                    self._export_to_path(image, out_path, fmt, quality, True)
                    exported.append({
                        "file_path": out_path,
                        "name": raw_name,
                        "width": image.get_width(),
                        "height": image.get_height(),
                    })
                except Exception as ex:
                    errors.append({"index": idx, "error": str(ex)})

            return {
                "status": "success",
                "results": {"exported": exported, "count": len(exported), "errors": errors}
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 2 — Image Adjustments
    # =========================================================================

    def _auto_levels(self, params):
        """Auto-stretch levels on a drawable."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-levels-stretch")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    proc.run(cfg)
                else:
                    proc2 = pdb.lookup_procedure("gimp-drawable-levels")
                    if proc2:
                        cfg2 = proc2.create_config()
                        cfg2.set_property("drawable", drawable)
                        cfg2.set_property("channel", Gimp.HistogramChannel.VALUE)
                        cfg2.set_property("low-input", 0.0)
                        cfg2.set_property("high-input", 1.0)
                        cfg2.set_property("clamp-input", True)
                        cfg2.set_property("gamma", 1.0)
                        cfg2.set_property("low-output", 0.0)
                        cfg2.set_property("high-output", 1.0)
                        proc2.run(cfg2)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 16 — Extended Export / Clipboard
    # =========================================================================

    def _paste_from_clipboard(self, params):
        """Paste the system clipboard as a new layer (or into the active)."""
        try:
            image_index  = int(params.get("image_index", 0))
            as_new_layer = bool(params.get("as_new_layer", True))
            layer_name   = (params.get("layer_name") or "").strip()
            image = self._get_image(image_index)
            pdb = Gimp.get_pdb()
            if as_new_layer:
                proc = pdb.lookup_procedure("gimp-edit-paste-as-new-layer")
                if proc is None:
                    # Fall back to Gimp.edit_paste which is context-sensitive
                    pasted = Gimp.edit_paste(self._resolve_layer(image, None, None), False)
                    return {"status": "success", "results": {
                        "status": "success", "pasted": bool(pasted),
                    }}
                cfg = proc.create_config()
                cfg.set_property("image", image)
                result = proc.run(cfg)
                try:
                    new_layer = result.index(0) if result is not None else None
                except Exception:
                    new_layer = None
                if new_layer is not None and layer_name:
                    try: new_layer.set_name(layer_name)
                    except Exception: pass
                Gimp.displays_flush()
                return {"status": "success", "results": {
                    "status": "success",
                    "layer_id":   new_layer.get_id()   if new_layer is not None else None,
                    "layer_name": new_layer.get_name() if new_layer is not None else None,
                }}
            else:
                drawable = self._resolve_layer(image, None, None)
                pasted_n = Gimp.edit_paste(drawable, False)
                Gimp.displays_flush()
                return {"status": "success", "results": {
                    "status": "success", "pasted": bool(pasted_n),
                }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _copy_selection_to_clipboard(self, params):
        """Copy the current selection (from the active drawable) to the clipboard."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            drawable = self._resolve_layer(image, None, None)
            ok = Gimp.edit_copy([drawable])
            return {"status": "success", "results": {"status": "success", "copied": bool(ok)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _copy_layer_to_clipboard(self, params):
        """Copy an entire named layer to the clipboard."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            ok = Gimp.edit_copy([layer])
            return {"status": "success", "results": {
                "status": "success", "copied": bool(ok), "layer_name": layer.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_via_fmt(self, params, fmt, extra_params=None):
        """Shared helper: route _export_image for a specific format + extra props."""
        p = dict(params)
        p.setdefault("format", fmt)
        if extra_params:
            for k, v in extra_params.items():
                p.setdefault(k, v)
        return self._export_image(p)

    def _export_webp(self, params):
        """Export as WebP with optional lossless / animation hints."""
        try:
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            quality     = int(params.get("quality", 85))
            lossless    = bool(params.get("lossless", False))
            animation   = bool(params.get("animation", False))
            image = self._get_image(image_index)
            extra = {"lossless": lossless}
            if animation:
                extra["animation"] = True
            size = self._export_to_path(image, file_path, "webp", quality, True, extra or None)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path,
                "file_size_bytes": size, "lossless": lossless, "animation": animation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_psd(self, params):
        """Export as PSD (layered) via gimp-file-save equivalent.

        Uses the .psd-driven Gimp.file_save path for maximum compatibility
        across 3.2 builds, so the compatibility flag only influences hints
        callers may check later.
        """
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            if not file_path:
                return {"status": "error", "error": "export_psd: 'file_path' is required"}
            image = self._get_image(image_index)
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(file_path), None)
            size = os.path.getsize(file_path) if os.path.exists(file_path) else None
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path, "file_size_bytes": size,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _import_psd(self, params):
        """Load a PSD file as a new image via Gimp.file_load."""
        try:
            from gi.repository import Gio
            file_path = params.get("file_path", "")
            if not file_path:
                return {"status": "error", "error": "import_psd: 'file_path' is required"}
            gio_file = Gio.File.new_for_path(file_path)
            image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gio_file)
            if image is None:
                return {"status": "error", "error": f"could not load: {file_path}"}
            Gimp.Display.new(image)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success",
                "image_id":   image.get_id(),
                "width":      image.get_width(),
                "height":     image.get_height(),
                "num_layers": len(image.get_layers()),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_tiff(self, params):
        """Export as TIFF with optional compression property."""
        try:
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            compression = params.get("compression", "lzw")
            image = self._get_image(image_index)
            COMPRESSION_MAP = {
                "none": 0, "lzw": 1, "packbits": 2,
                "adobe-deflate": 3, "jpeg": 4,
                "ccitt-g3": 5, "ccitt-g4": 6,
            }
            extra = {"compression": COMPRESSION_MAP.get(compression, 1)}
            size = self._export_to_path(image, file_path, "tiff", 90, True, extra)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path,
                "file_size_bytes": size, "compression": compression,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_hdr(self, params):
        """Export as Radiance HDR via Gimp.file_save (.hdr extension drives format)."""
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            if not file_path:
                return {"status": "error", "error": "export_hdr: 'file_path' is required"}
            image = self._get_image(image_index)
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(file_path), None)
            size = os.path.getsize(file_path) if os.path.exists(file_path) else None
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path, "file_size_bytes": size,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_exr(self, params):
        """Export as OpenEXR via Gimp.file_save (.exr extension drives format)."""
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            half_float  = bool(params.get("half_float", True))
            if not file_path:
                return {"status": "error", "error": "export_exr: 'file_path' is required"}
            image = self._get_image(image_index)
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(file_path), None)
            size = os.path.getsize(file_path) if os.path.exists(file_path) else None
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path,
                "file_size_bytes": size, "half_float": half_float,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_gif_animation(self, params):
        """Export the current image as an animated GIF.

        Callers are expected to have arranged their frames as layers in
        bottom-to-top order. Delay and loop-count are encoded in GIMP's
        layer-name conventions ((100ms) suffix etc.) when 'use_layer_names'
        is true, otherwise via PDB properties.
        """
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path") or ""
            delay_ms    = int(params.get("delay_ms", 100))
            loop_count  = int(params.get("loop_count", 0))
            dither      = bool(params.get("dither", True))
            if not file_path:
                return {"status": "error", "error": "export_gif_animation: 'file_path' is required"}
            image = self._get_image(image_index)
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("file-gif-export")
            if proc is None:
                proc = pdb.lookup_procedure("file-gif-save")
            if proc is None:
                return {"status": "error", "error": "no GIF export procedure available"}
            cfg = proc.create_config()
            cfg.set_property("image", image)
            cfg.set_property("file",  Gio.File.new_for_path(file_path))
            try: cfg.set_property("as-animation", True)
            except Exception: pass
            try: cfg.set_property("loop",         loop_count == 0)
            except Exception: pass
            try: cfg.set_property("default-delay", delay_ms)
            except Exception: pass
            try: cfg.set_property("dither",        dither)
            except Exception: pass
            proc.run(cfg)
            size = os.path.getsize(file_path) if os.path.exists(file_path) else None
            return {"status": "success", "results": {
                "status": "success", "file_path": file_path,
                "file_size_bytes": size, "delay_ms": delay_ms,
                "loop_count": loop_count, "dither": dither,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_animated_sprite_strip(self, params):
        """Export the active image's layers as a horizontal/vertical sprite strip.

        Thin wrapper over the existing _export_sprite_sheet with explicit
        orientation semantics.
        """
        try:
            p = dict(params)
            orient = (p.pop("orientation", "horizontal") or "horizontal").lower()
            if orient == "vertical":
                p["columns"] = 1
            else:
                p["rows"] = 1
            return self._export_sprite_sheet(p)
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 17 — Scripting / Macros
    # =========================================================================

    def _run_pdb_procedure(self, params):
        """Execute a PDB procedure with a dict of property values.

        Dispatches through lookup_procedure + create_config + set_property
        per key + run. Returns the raw GValueArray index 0+ if the caller
        set return_as_list=True; otherwise returns a generic success.
        """
        try:
            name = params.get("name") or ""
            args = params.get("args") or {}
            if not name:
                return {"status": "error", "error": "run_pdb_procedure: 'name' is required"}
            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure(name)
            if proc is None:
                return {"status": "error", "error": f"PDB procedure not found: {name}"}
            cfg = proc.create_config()
            applied = []
            for k, v in (args.items() if isinstance(args, dict) else []):
                try:
                    cfg.set_property(k, v)
                    applied.append(k)
                except Exception:
                    pass
            result = proc.run(cfg)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":   "success",
                "name":     name,
                "applied":  applied,
                "ran":      True,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _run_script_fu(self, params):
        """Execute a Script-Fu snippet via gimp-script-fu-eval.

        Script-Fu is still supported in 3.2 through the PDB procedure
        gimp-script-fu-eval. Useful for quick one-liners against legacy
        Scheme-based tooling without leaving Python.
        """
        try:
            code = params.get("script") or params.get("code") or ""
            if not code:
                return {"status": "error", "error": "run_script_fu: 'script' is required"}
            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure("script-fu-eval") or pdb.lookup_procedure("gimp-script-fu-eval")
            if proc is None:
                return {"status": "error",
                        "error": "script-fu-eval not available in this GIMP build"}
            cfg = proc.create_config()
            try: cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
            except Exception: pass
            try: cfg.set_property("code",     code)
            except Exception:
                try: cfg.set_property("script", code)
                except Exception: pass
            proc.run(cfg)
            return {"status": "success", "results": {
                "status": "success", "executed_chars": len(code),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _record_macro(self, params):
        """Start capturing subsequent tool calls into a named macro.

        Stores the macro name on the plugin instance. Subsequent calls to
        execute_command check _active_macro and append to the in-memory
        log until stop_recording clears it.
        """
        name = (params.get("name") or "").strip()
        if not name:
            return {"status": "error", "error": "record_macro: 'name' is required"}
        if not hasattr(self, "_macros"):
            self._macros = {}
        self._active_macro = name
        self._macros[name] = []
        return {"status": "success", "results": {
            "status": "success", "name": name, "active": True,
        }}

    def _stop_recording(self, _params):
        """Stop capturing the active macro (if any)."""
        if not hasattr(self, "_macros") or not getattr(self, "_active_macro", None):
            return {"status": "error", "error": "stop_recording: no macro is currently recording"}
        name = self._active_macro
        self._active_macro = None
        return {"status": "success", "results": {
            "status": "success", "name": name,
            "steps":  len(self._macros.get(name, [])),
        }}

    def _replay_macro(self, params):
        """Re-run the steps captured in a named macro via the same dispatcher."""
        name = params.get("name") or ""
        if not name:
            return {"status": "error", "error": "replay_macro: 'name' is required"}
        steps = (getattr(self, "_macros", {}) or {}).get(name)
        if steps is None:
            return {"status": "error", "error": f"macro not found: {name}"}
        results = []
        for step in steps:
            try:
                results.append(self.execute_command(json.dumps(step)))
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
        return {"status": "success", "results": {
            "status":  "success",
            "name":    name,
            "steps":   len(steps),
            "results": results,
        }}

    def _list_macros(self, _params):
        """Return the names of all recorded macros."""
        names = sorted((getattr(self, "_macros", {}) or {}).keys())
        return {"status": "success", "results": {
            "status": "success", "count": len(names), "macros": names,
        }}

    def _delete_macro(self, params):
        """Discard a previously recorded macro by name."""
        name = params.get("name") or ""
        if not name:
            return {"status": "error", "error": "delete_macro: 'name' is required"}
        macros = getattr(self, "_macros", {}) or {}
        if name not in macros:
            return {"status": "error", "error": f"macro not found: {name}"}
        macros.pop(name, None)
        if getattr(self, "_active_macro", None) == name:
            self._active_macro = None
        return {"status": "success", "results": {"status": "success", "name": name}}

    # =========================================================================
    # CATEGORY 18 — Sessions
    # =========================================================================

    def _save_workspace(self, params):
        """Persist the current GIMP workspace as a multi-image XCF bundle.

        Saves each open image as <path>/image_N.xcf plus a manifest.json
        that records active image index, open file paths, and layer
        visibility for each image. Not a perfect reproduction of window
        positions (3.2's PDB doesn't expose per-display coordinates), but
        enough for agent loops to pick up where they left off.
        """
        try:
            workspace_dir = params.get("path") or ""
            if not workspace_dir:
                return {"status": "error", "error": "save_workspace: 'path' is required"}
            os.makedirs(workspace_dir, exist_ok=True)
            images = Gimp.get_images()
            manifest = {"images": []}
            for idx, image in enumerate(images):
                xcf_path = os.path.join(workspace_dir, f"image_{idx}.xcf")
                self._save_xcf({"image_index": idx, "file_path": xcf_path})
                manifest["images"].append({
                    "index":     idx,
                    "image_id":  image.get_id(),
                    "xcf_path":  xcf_path,
                    "width":     image.get_width(),
                    "height":    image.get_height(),
                    "layers":    [{"name": l.get_name(), "visible": bool(l.get_visible())}
                                  for l in (image.get_layers() or [])],
                })
            manifest_path = os.path.join(workspace_dir, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            return {"status": "success", "results": {
                "status": "success", "path": workspace_dir,
                "images": len(images), "manifest": manifest_path,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _load_workspace(self, params):
        """Restore a workspace saved by _save_workspace."""
        try:
            from gi.repository import Gio
            workspace_dir = params.get("path") or ""
            manifest_path = os.path.join(workspace_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                return {"status": "error", "error": f"manifest not found: {manifest_path}"}
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            loaded = []
            for entry in manifest.get("images", []):
                xcf_path = entry.get("xcf_path", "")
                if not os.path.exists(xcf_path):
                    continue
                gio_file = Gio.File.new_for_path(xcf_path)
                image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gio_file)
                if image is None:
                    continue
                try: Gimp.Display.new(image)
                except Exception: pass
                loaded.append({"xcf_path": xcf_path, "image_id": image.get_id()})
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":  "success",
                "loaded":  len(loaded),
                "images":  loaded,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 15 — Guides / Grid / Sample Points
    # =========================================================================

    def _add_guide(self, params):
        """Add a horizontal or vertical guide. Returns the new guide_id."""
        try:
            image_index = int(params.get("image_index", 0))
            orientation = (params.get("orientation") or "horizontal").lower()
            position    = int(params.get("position", 0))
            image = self._get_image(image_index)
            if orientation.startswith("h"):
                guide_id = image.add_hguide(position)
            elif orientation.startswith("v"):
                guide_id = image.add_vguide(position)
            else:
                return {"status": "error",
                        "error": f"add_guide: orientation must be 'horizontal' or 'vertical'"}
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":      "success",
                "guide_id":    int(guide_id),
                "orientation": orientation,
                "position":    position,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_guides(self, params):
        """Iterate the image's guides via find_next_guide."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            guides = []
            gid = image.find_next_guide(0)
            while gid:
                try:
                    orient = image.get_guide_orientation(gid)
                    orient_str = ("horizontal" if orient == Gimp.OrientationType.HORIZONTAL
                                  else "vertical" if orient == Gimp.OrientationType.VERTICAL
                                  else str(orient))
                except Exception:
                    orient_str = "unknown"
                try:
                    pos = int(image.get_guide_position(gid))
                except Exception:
                    pos = None
                guides.append({"id": int(gid), "orientation": orient_str, "position": pos})
                gid = image.find_next_guide(gid)
            return {"status": "success", "results": {
                "status": "success", "count": len(guides), "guides": guides,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _remove_guide(self, params):
        """Delete a specific guide by id."""
        try:
            image_index = int(params.get("image_index", 0))
            guide_id    = int(params.get("guide_id"))
            image = self._get_image(image_index)
            image.delete_guide(guide_id)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "guide_id": guide_id}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _remove_all_guides(self, params):
        """Iterate the image's guides and delete each one."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            removed = 0
            gid = image.find_next_guide(0)
            while gid:
                next_gid = image.find_next_guide(gid)
                image.delete_guide(gid)
                removed += 1
                gid = next_gid
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "removed": removed,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_grid(self, params):
        """Set grid spacing / offset / style / foreground color."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            sx = params.get("spacing_x")
            sy = params.get("spacing_y")
            if sx is not None and sy is not None:
                image.grid_set_spacing(float(sx), float(sy))
            ox = params.get("offset_x")
            oy = params.get("offset_y")
            if ox is not None and oy is not None:
                image.grid_set_offset(float(ox), float(oy))
            style = params.get("style")
            if style:
                STYLE_MAP = {
                    "dots":           "DOTS",
                    "intersections":  "INTERSECTIONS",
                    "lines":          "SOLID",
                    "solid":          "SOLID",
                    "dashed":         "ON_OFF_DASH",
                    "double-dashed":  "DOUBLE_DASH",
                }
                enum_name = STYLE_MAP.get(style.lower(), style.upper())
                style_enum = getattr(Gimp.GridStyle, enum_name, None)
                if style_enum is not None:
                    image.grid_set_style(style_enum)
            foreground = params.get("foreground")
            if foreground:
                image.grid_set_foreground_color(Gegl.Color.new(foreground))
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_grid(self, params):
        """Read grid spacing / offset / style / color."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            spacing = image.grid_get_spacing()
            offset  = image.grid_get_offset()
            style_enum = image.grid_get_style()
            fg_color   = image.grid_get_foreground_color()
            def _pair(t):
                if isinstance(t, tuple):
                    if len(t) == 3:
                        return [float(t[1]), float(t[2])]
                    if len(t) == 2:
                        return [float(t[0]), float(t[1])]
                return None
            return {"status": "success", "results": {
                "status": "success",
                "spacing": _pair(spacing),
                "offset":  _pair(offset),
                "style":   str(style_enum),
                "foreground": self._color_to_hex(fg_color),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _toggle_grid_visible(self, _params):
        return {"status": "error",
                "error": "toggle_grid_visible: grid visibility is a UI state (View → Show Grid) "
                         "and is not exposed via Gimp.Image or the PDB in 3.2. "
                         "Use the UI or View menu from inside GIMP."}

    def _snap_to_grid(self, _params):
        return {"status": "error",
                "error": "snap_to_grid: snap state is UI-only in GIMP 3.2. "
                         "Use View → Snap to Grid from inside GIMP."}

    def _snap_to_guides(self, _params):
        return {"status": "error",
                "error": "snap_to_guides: snap state is UI-only in GIMP 3.2. "
                         "Use View → Snap to Guides from inside GIMP."}

    def _snap_to_canvas_edges(self, _params):
        return {"status": "error",
                "error": "snap_to_canvas_edges: snap state is UI-only in GIMP 3.2. "
                         "Use View → Snap to Canvas Edges from inside GIMP."}

    def _add_sample_point(self, params):
        """Add a sample point at (x, y). Returns the new sample_point_id."""
        try:
            image_index = int(params.get("image_index", 0))
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            image = self._get_image(image_index)
            sp_id = image.add_sample_point(x, y)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "sample_point_id": int(sp_id), "x": x, "y": y,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_sample_points(self, params):
        """Iterate sample points via find_next_sample_point."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            points = []
            spid = image.find_next_sample_point(0)
            while spid:
                try:
                    pos = image.get_sample_point_position(spid)
                except Exception:
                    pos = None
                if isinstance(pos, tuple) and len(pos) >= 3:
                    px, py = int(pos[1]), int(pos[2])
                elif isinstance(pos, tuple) and len(pos) == 2:
                    px, py = int(pos[0]), int(pos[1])
                else:
                    px, py = None, None
                points.append({"id": int(spid), "x": px, "y": py})
                spid = image.find_next_sample_point(spid)
            return {"status": "success", "results": {
                "status": "success", "count": len(points), "sample_points": points,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _remove_sample_point(self, params):
        """Delete a specific sample point by id."""
        try:
            image_index = int(params.get("image_index", 0))
            sp_id = int(params.get("sample_point_id"))
            image = self._get_image(image_index)
            image.delete_sample_point(sp_id)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "sample_point_id": sp_id,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_brushes(self, params):
        """List available brushes via Gimp.brushes_get_list."""
        try:
            filter_str = params.get("filter") or ""
            names = Gimp.brushes_get_list(filter_str) or []
            return {"status": "success", "results": {
                "status": "success", "count": len(names), "filter": filter_str,
                "brushes": list(names),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_dynamics(self, params):
        """List available dynamics presets.

        GIMP 3.2.2 does not expose Gimp.dynamics_get_list; we fall back to
        Gimp.context_get_dynamics_name + probing the user dynamics directory.
        """
        try:
            dynamics = []
            # Probe standard user/system dynamics directories via PDB
            pdb = Gimp.get_pdb()
            for proc_name in ("gimp-dynamics-refresh", "gimp-dynamics-get-list"):
                proc = pdb.lookup_procedure(proc_name)
                if proc is not None and proc_name == "gimp-dynamics-get-list":
                    cfg = proc.create_config()
                    try:
                        cfg.set_property("filter", params.get("filter") or "")
                    except Exception: pass
                    try:
                        res = proc.run(cfg)
                        raw = res.index(0) if res else None
                        if raw is not None:
                            dynamics = list(raw)
                    except Exception:
                        pass
            if not dynamics:
                # Last-ditch: return the current dynamics name if nothing else worked.
                try:
                    current = Gimp.context_get_dynamics_name()
                    if current:
                        dynamics = [current]
                except Exception:
                    pass
            return {"status": "success", "results": {
                "status":   "success",
                "count":    len(dynamics),
                "dynamics": dynamics,
                "note":     "GIMP 3.2 does not expose a full dynamics list API; "
                            "fallback returns the active dynamics only.",
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_patterns(self, params):
        """List available patterns via Gimp.patterns_get_list."""
        try:
            filter_str = params.get("filter") or ""
            names = Gimp.patterns_get_list(filter_str) or []
            return {"status": "success", "results": {
                "status": "success", "count": len(names), "filter": filter_str,
                "patterns": list(names),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_gradients(self, params):
        """List available gradients via Gimp.gradients_get_list."""
        try:
            filter_str = params.get("filter") or ""
            names = Gimp.gradients_get_list(filter_str) or []
            return {"status": "success", "results": {
                "status": "success", "count": len(names), "filter": filter_str,
                "gradients": list(names),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_pdb_procedures(self, params):
        """List PDB procedures matching an optional substring filter.

        Uses gimp-pdb-query which accepts multiple regex filters; we feed
        the user-supplied substring as the `proc-name` pattern and match
        every other field with '.*' to keep the query broad.
        """
        try:
            filter_str = params.get("filter") or ""
            needle = filter_str.strip() or ".*"
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-pdb-query")
            if proc is None:
                return {"status": "error", "error": "gimp-pdb-query not available"}
            cfg = proc.create_config()
            for prop, val in (
                ("name",       needle),
                ("blurb",      ".*"),
                ("help",       ".*"),
                ("authors",    ".*"),
                ("copyright",  ".*"),
                ("date",       ".*"),
                ("proc-type",  ".*"),
            ):
                try: cfg.set_property(prop, val)
                except Exception: pass
            result = proc.run(cfg)
            names = []
            try:
                # gimp-pdb-query returns (count, [names]) in some bindings.
                raw = result.index(1) if result is not None else None
                if raw is not None:
                    names = list(raw)
            except Exception:
                pass
            return {"status": "success", "results": {
                "status":     "success",
                "filter":     filter_str,
                "count":      len(names),
                "procedures": names,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _create_brush_from_selection(self, params):
        """Create a new brush from the current selection of the active drawable.

        Uses gimp-image-convert-to-brush if available; otherwise falls back
        to saving the selection content as a GBR file via PDB.
        """
        _ = params
        return {"status": "error",
                "error": "create_brush_from_selection: no direct PDB procedure in GIMP 3.2; "
                         "export the selection as .gbr via export_image to a path inside "
                         "the user brushes folder, then call a future refresh tool."}

    def _create_pattern_from_selection(self, params):
        """Create a new pattern from the current selection of the active drawable."""
        _ = params
        return {"status": "error",
                "error": "create_pattern_from_selection: no direct PDB procedure in GIMP 3.2; "
                         "export the selection as .pat via export_image to a path inside "
                         "the user patterns folder, then call a future refresh tool."}

    def _delete_brush(self, params):
        """Delete a named brush via gimp-brush-delete."""
        try:
            name = params.get("name") or ""
            if not name:
                return {"status": "error", "error": "delete_brush: 'name' is required"}
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-brush-delete")
            if proc is None:
                return {"status": "error", "error": "gimp-brush-delete not available"}
            cfg = proc.create_config()
            brush = Gimp.Brush.get_by_name(name) if hasattr(Gimp, "Brush") else None
            if brush is None:
                return {"status": "error", "error": f"brush not found: {name}"}
            try: cfg.set_property("brush", brush)
            except Exception: pass
            proc.run(cfg)
            try: Gimp.brushes_refresh()
            except Exception: pass
            return {"status": "success", "results": {"status": "success", "name": name}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _delete_pattern(self, params):
        """Delete a named pattern via gimp-pattern-delete (if available)."""
        try:
            name = params.get("name") or ""
            if not name:
                return {"status": "error", "error": "delete_pattern: 'name' is required"}
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-pattern-delete")
            if proc is None:
                return {"status": "error",
                        "error": "gimp-pattern-delete not available in this GIMP build"}
            pattern = Gimp.Pattern.get_by_name(name) if hasattr(Gimp, "Pattern") else None
            if pattern is None:
                return {"status": "error", "error": f"pattern not found: {name}"}
            cfg = proc.create_config()
            try: cfg.set_property("pattern", pattern)
            except Exception: pass
            proc.run(cfg)
            try: Gimp.patterns_refresh()
            except Exception: pass
            return {"status": "success", "results": {"status": "success", "name": name}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _load_icc_bytes(self, file_path):
        """Read ICC profile bytes from disk. Raises FileNotFoundError if missing."""
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"ICC profile file not found: {file_path}")
        with open(file_path, "rb") as f:
            return f.read()

    def _apply_color_profile(self, params):
        """Convert an image to a new ICC profile — same as convert_to_profile."""
        return self._convert_to_profile(params)

    def _convert_to_profile(self, params):
        """Convert an image's pixel data through a new ICC profile.

        Uses Image.convert_color_profile with the on-disk profile bytes
        loaded into a GLib.Bytes buffer.
        """
        try:
            from gi.repository import GLib
            image_index   = int(params.get("image_index", 0))
            profile_path  = params.get("profile_path") or ""
            intent_str    = (params.get("intent") or "perceptual").lower()
            INTENT_MAP = {
                "perceptual":             "PERCEPTUAL",
                "relative":               "RELATIVE_COLORIMETRIC",
                "relative-colorimetric":  "RELATIVE_COLORIMETRIC",
                "saturation":             "SATURATION",
                "absolute":               "ABSOLUTE_COLORIMETRIC",
                "absolute-colorimetric":  "ABSOLUTE_COLORIMETRIC",
            }
            intent_enum_name = INTENT_MAP.get(intent_str, "PERCEPTUAL")
            intent = getattr(Gimp.ColorRenderingIntent, intent_enum_name,
                             Gimp.ColorRenderingIntent.PERCEPTUAL)
            bytes_data = self._load_icc_bytes(profile_path)
            gbytes = GLib.Bytes.new(bytes_data)
            image = self._get_image(image_index)
            image.convert_color_profile(gbytes, intent, bool(params.get("bpc", True)))
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "profile_path": profile_path,
                "intent":       intent_str,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _assign_profile(self, params):
        """Tag an image with a new ICC profile without converting pixels."""
        try:
            from gi.repository import GLib
            image_index  = int(params.get("image_index", 0))
            profile_path = params.get("profile_path") or ""
            bytes_data = self._load_icc_bytes(profile_path)
            gbytes = GLib.Bytes.new(bytes_data)
            image = self._get_image(image_index)
            image.set_color_profile(gbytes)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "profile_path": profile_path,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_current_profile(self, params):
        """Return the ICC profile currently tagged on the image.

        Returns a description where possible. The raw bytes are not sent
        across the wire — callers that need them should write the image
        out and inspect the file.
        """
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            profile = None
            try:
                profile = image.get_color_profile()
            except Exception:
                profile = None
            if profile is None:
                return {"status": "success", "results": {
                    "status":      "success",
                    "has_profile": False,
                }}
            description = None
            for attr in ("get_description", "get_label"):
                try:
                    fn = getattr(profile, attr, None)
                    if fn is not None:
                        description = fn()
                        if description:
                            break
                except Exception:
                    continue
            size = None
            try:
                raw = profile.get_data() if hasattr(profile, "get_data") else None
                if raw is not None:
                    size = len(bytes(raw))
            except Exception:
                pass
            return {"status": "success", "results": {
                "status":      "success",
                "has_profile": True,
                "description": description,
                "size_bytes":  size,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _load_palette(self, params):
        """Load a GIMP .gpl palette file and install it as a named palette.

        Parses the text .gpl format (header + r g b name rows), creates a
        Gimp.Palette, and adds each entry. Returns the created palette's
        name and entry count.
        """
        try:
            from gi.repository import Gegl
            file_path = params.get("file_path") or ""
            override_name = (params.get("name") or "").strip()
            if not file_path:
                return {"status": "error", "error": "load_palette: 'file_path' is required"}
            if not os.path.exists(file_path):
                return {"status": "error", "error": f"file not found: {file_path}"}

            parsed_name = None
            entries = []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.startswith("GIMP Palette"):
                        continue
                    if s.lower().startswith("name:"):
                        parsed_name = s.split(":", 1)[1].strip()
                        continue
                    if s.lower().startswith("columns:"):
                        continue
                    parts = s.split(None, 3)
                    if len(parts) < 3:
                        continue
                    try:
                        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    except ValueError:
                        continue
                    ename = parts[3] if len(parts) >= 4 else ""
                    entries.append((r, g, b, ename))

            if not entries:
                return {"status": "error", "error": "no usable color entries in file"}

            palette_name = override_name or parsed_name or os.path.splitext(os.path.basename(file_path))[0]
            palette = Gimp.Palette.new(palette_name)
            if palette is None:
                return {"status": "error", "error": f"could not create palette '{palette_name}'"}
            for r, g, b, ename in entries:
                hex_color = "#{:02x}{:02x}{:02x}".format(r & 0xFF, g & 0xFF, b & 0xFF)
                try: palette.add_entry(ename, Gegl.Color.new(hex_color))
                except Exception: pass
            return {"status": "success", "results": {
                "status":       "success",
                "palette_name": palette.get_name(),
                "entries":      len(entries),
                "source":       file_path,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _save_palette(self, params):
        """Create a new palette with the given name and list of colors."""
        try:
            from gi.repository import Gegl
            name   = (params.get("name") or "").strip()
            colors = params.get("colors") or []
            if not name:
                return {"status": "error", "error": "save_palette: 'name' is required"}
            if not isinstance(colors, list) or not colors:
                return {"status": "error", "error": "save_palette: 'colors' must be a non-empty list"}
            palette = Gimp.Palette.new(name)
            if palette is None:
                return {"status": "error", "error": f"could not create palette '{name}'"}
            for i, c in enumerate(colors):
                if isinstance(c, dict):
                    col_str = c.get("hex") or c.get("color") or ""
                    entry_name = c.get("name") or f"color_{i}"
                else:
                    col_str = str(c)
                    entry_name = f"color_{i}"
                if not col_str:
                    continue
                try: palette.add_entry(entry_name, Gegl.Color.new(col_str))
                except Exception: pass
            return {"status": "success", "results": {
                "status":       "success",
                "palette_name": palette.get_name(),
                "entries":      len(colors),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_palettes(self, params):
        """List palette names via Gimp.palettes_get_list."""
        try:
            filter_str = params.get("filter") or ""
            names = Gimp.palettes_get_list(filter_str) or []
            return {"status": "success", "results": {
                "status":   "success",
                "count":    len(names),
                "filter":   filter_str,
                "palettes": list(names),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_palette_color(self, params):
        """Return one specific color from a named palette by index."""
        try:
            name  = params.get("name") or ""
            index = int(params.get("index", 0))
            if not name:
                return {"status": "error", "error": "get_palette_color: 'name' is required"}
            palette = Gimp.Palette.get_by_name(name)
            if palette is None:
                return {"status": "error", "error": f"palette not found: {name}"}
            colors = palette.get_colors() or []
            if not 0 <= index < len(colors):
                return {"status": "error",
                        "error": f"index {index} out of range (palette has {len(colors)} entries)"}
            hex_color = self._color_to_hex(colors[index])
            return {"status": "success", "results": {
                "status":       "success",
                "palette_name": name,
                "index":        index,
                "hex":          hex_color,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_dominant_colors(self, params):
        """Extract top-k dominant colors from a layer via downsample + bucket-count.

        Downscales a transient copy of the layer to `sample_size` on the
        long edge, iterates the scaled pixels once, bins each pixel into
        a 32-step RGB bucket, and returns the top-k buckets by population.
        A fast approximation — not true k-means but deterministic and
        cheap enough to call per-layer in agent loops.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            k           = int(params.get("k", 5))
            ignore_alpha = bool(params.get("ignore_alpha", True))
            sample_size = int(params.get("sample_size", 48))

            image    = self._get_image(image_index)
            src_layer = self._resolve_layer(image, layer_name, None)
            # Duplicate into a temp image so the scale is non-destructive.
            tmp_image = image.duplicate()
            try:
                # Flatten so the duplicate has a single drawable to sample.
                tmp_image.flatten()
                # Scale to sample_size on the long edge.
                iw, ih = tmp_image.get_width(), tmp_image.get_height()
                long_edge = max(iw, ih)
                if long_edge > sample_size:
                    scale = sample_size / long_edge
                    tmp_image.scale(max(1, int(iw * scale)), max(1, int(ih * scale)))
                sampled = tmp_image.get_layers()[0]
                w, h = sampled.get_width(), sampled.get_height()
                buckets = {}
                for yy in range(h):
                    for xx in range(w):
                        try:
                            res = sampled.get_pixel(xx, yy)
                        except Exception:
                            continue
                        # get_pixel returns (num_channels, [values])
                        if isinstance(res, tuple) and len(res) >= 2:
                            chans = res[1] or []
                        else:
                            chans = list(res or [])
                        if len(chans) < 3:
                            continue
                        if ignore_alpha and len(chans) >= 4 and chans[3] < 10:
                            continue
                        key = (int(chans[0]) // 32, int(chans[1]) // 32, int(chans[2]) // 32)
                        buckets[key] = buckets.get(key, 0) + 1
            finally:
                try: tmp_image.delete()
                except Exception: pass

            top = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:k]
            def _hex(r, g, b):
                return "#{:02x}{:02x}{:02x}".format(
                    min(255, r * 32 + 16),
                    min(255, g * 32 + 16),
                    min(255, b * 32 + 16))
            colors = [{
                "hex":   _hex(key[0], key[1], key[2]),
                "rgb":   [key[0] * 32 + 16, key[1] * 32 + 16, key[2] * 32 + 16],
                "count": count,
            } for key, count in top]
            return {"status": "success", "results": {
                "status": "success",
                "layer_name":  src_layer.get_name(),
                "k":           len(colors),
                "sample_size": sample_size,
                "colors":      colors,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_average_color(self, params):
        """Sample mean RGBA in a rectangular region of a layer.

        Uses gimp-drawable-histogram per channel to avoid pixel-by-pixel
        iteration. Region coordinates are layer-local.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x           = int(params.get("x", 0))
            y           = int(params.get("y", 0))
            width       = int(params.get("width", 0))
            height      = int(params.get("height", 0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            if width <= 0 or height <= 0:
                width, height = drawable.get_width() - x, drawable.get_height() - y
            # Make a selection over the region, measure histogram means, restore.
            Gimp.Selection.none(image)
            image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, width, height)

            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-drawable-histogram")
            def _mean(channel_enum):
                if proc is None:
                    return 0.0
                cfg = proc.create_config()
                cfg.set_property("drawable",    drawable)
                cfg.set_property("channel",     channel_enum)
                cfg.set_property("start-range", 0.0)
                cfg.set_property("end-range",   1.0)
                res = proc.run(cfg)
                try: return float(res.index(0))
                except Exception: return 0.0

            r = _mean(Gimp.HistogramChannel.RED)
            g = _mean(Gimp.HistogramChannel.GREEN)
            b = _mean(Gimp.HistogramChannel.BLUE)
            try:    a = _mean(Gimp.HistogramChannel.ALPHA)
            except Exception: a = 1.0
            Gimp.Selection.none(image)
            Gimp.displays_flush()

            def _u8(v): return max(0, min(255, int(v * 255)))
            hex_color = "#{:02x}{:02x}{:02x}".format(_u8(r), _u8(g), _u8(b))
            return {"status": "success", "results": {
                "status": "success",
                "layer_name":  drawable.get_name(),
                "region":      {"x": x, "y": y, "width": width, "height": height},
                "rgba":        [r, g, b, a],
                "hex":         hex_color,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_background(self, params):
        """Set the paint-context background color."""
        try:
            from gi.repository import Gegl
            color_str = params.get("color", "")
            if not color_str:
                return {"status": "error", "error": "set_background: 'color' is required"}
            Gimp.context_set_background(Gegl.Color.new(color_str))
            return {"status": "success", "results": {
                "status": "success", "color": color_str,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _swap_colors(self, _params):
        """Swap the paint-context foreground and background colors."""
        try:
            Gimp.context_swap_colors()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_foreground(self, params):
        """Set the paint-context foreground color."""
        try:
            from gi.repository import Gegl
            color_str = params.get("color", "")
            if not color_str:
                return {"status": "error", "error": "set_foreground: 'color' is required"}
            Gimp.context_set_foreground(Gegl.Color.new(color_str))
            return {"status": "success", "results": {
                "status": "success", "color": color_str,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_seamless_tile(self, params):
        """Apply gegl:tile-seamless to make a texture tile seamlessly."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:tile-seamless", {})
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_waterpixels(self, params):
        """Apply gegl:waterpixels — superpixel segmentation into flat regions."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            size        = int(params.get("size", 16))
            smoothness  = float(params.get("smoothness", 1.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:waterpixels", {
                    "size":       size,
                    "smoothness": smoothness,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "size": size, "smoothness": smoothness,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_cartoon(self, params):
        """Apply gegl:cartoon — cartoon edge + darken effect."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            mask_radius = float(params.get("mask_radius", 7))
            pct_black   = float(params.get("pct_black", 0.2))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:cartoon", {
                    "mask-radius": mask_radius,
                    "pct-black":   pct_black,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "mask_radius": mask_radius, "pct_black": pct_black,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_oilify(self, params):
        """Apply gegl:oilify — painterly smoothing filter."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            mask_radius = int(params.get("mask_radius", 4))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:oilify", {
                    "mask-radius": mask_radius,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "mask_radius": mask_radius,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_displacement(self, params):
        """Apply gegl:displace using named layers as x/y displacement maps."""
        try:
            image_index     = int(params.get("image_index", 0))
            layer_name      = params.get("layer_name", None)
            x_map_layer     = params.get("x_map_layer") or ""
            y_map_layer     = params.get("y_map_layer") or x_map_layer
            amount          = float(params.get("amount", 10.0))
            edge_behavior   = (params.get("edge_behavior") or "wrap").lower()

            ABYSS_MAP = {
                "wrap":  "loop",
                "smear": "clamp",
                "none":  "none",
                "black": "black",
                "white": "white",
            }
            abyss = ABYSS_MAP.get(edge_behavior, "loop")

            if not x_map_layer:
                return {"status": "error",
                        "error": "apply_displacement: 'x_map_layer' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            x_map    = self._resolve_layer(image, x_map_layer, None)
            y_map    = self._resolve_layer(image, y_map_layer, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:displace", {
                    "displace-mode": "cartesian",
                    "amount-x":      amount,
                    "amount-y":      amount,
                    "abyss-policy":  abyss,
                    "aux":           x_map,
                    "aux2":          y_map,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success",
                "layer_name":    drawable.get_name(),
                "x_map_layer":   x_map.get_name(),
                "y_map_layer":   y_map.get_name(),
                "amount":        amount,
                "edge_behavior": edge_behavior,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_bump_map(self, params):
        """Apply gegl:bump-map using a named layer as the height source."""
        try:
            image_index     = int(params.get("image_index", 0))
            layer_name      = params.get("layer_name", None)
            bump_layer_name = params.get("bump_layer_name") or ""
            azimuth         = float(params.get("azimuth", 135))
            elevation       = float(params.get("elevation", 45))
            depth           = float(params.get("depth", 3))
            if not bump_layer_name:
                return {"status": "error",
                        "error": "apply_bump_map: 'bump_layer_name' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            bump     = self._resolve_layer(image, bump_layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:bump-map", {
                    "aux":       bump,
                    "azimuth":   azimuth,
                    "elevation": elevation,
                    "depth":     depth,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success",
                "layer_name":      drawable.get_name(),
                "bump_layer_name": bump.get_name(),
                "azimuth":   azimuth,
                "elevation": elevation,
                "depth":     depth,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_color_to_alpha(self, params):
        """Apply gegl:color-to-alpha — drop a color out of the layer as transparency."""
        try:
            from gi.repository import Gegl
            image_index             = int(params.get("image_index", 0))
            layer_name              = params.get("layer_name", None)
            color_str               = params.get("color", "white")
            transparency_threshold  = float(params.get("transparency_threshold", 0.0))
            opacity_threshold       = float(params.get("opacity_threshold", 1.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:color-to-alpha", {
                    "color":                  Gegl.Color.new(color_str),
                    "transparency-threshold": transparency_threshold,
                    "opacity-threshold":      opacity_threshold,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "color": color_str,
                "transparency_threshold": transparency_threshold,
                "opacity_threshold":      opacity_threshold,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_despeckle(self, params):
        """Despeckle / noise reduction.

        GIMP 3.2 replaces the 2.x plug-in-despeckle with gegl:noise-reduction,
        which is a simpler neighborhood-filter primitive. A median-strength
        param drives iteration count; radius maps to the noise-reduction
        iterations since the op is discrete per pass.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            radius      = int(params.get("radius", 3))
            median      = float(params.get("median", 50))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            iterations = max(1, min(8, int(radius)))
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:noise-reduction", {
                    "iterations": iterations,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "radius": radius, "median": median, "iterations": iterations,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_bokeh(self, params):
        """Shaped bokeh blur.

        GIMP 3.2 does not ship a dedicated gegl:bokeh op in the core GEGL
        build. The API shape is retained so callers can target this tool
        across builds; in the current build it returns a structured
        'not available' error with a pointer to apply_lens_blur as the
        closest built-in alternative.
        """
        _ = params
        return {"status": "error",
                "error": "apply_bokeh: gegl:bokeh is not available in this GIMP 3.2 "
                         "build. Use apply_lens_blur for a radial/photographic "
                         "out-of-focus effect."}

    def _apply_lens_blur(self, params):
        """Apply gegl:lens-blur."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            radius      = float(params.get("radius", 5.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:lens-blur", {
                    "radius": radius,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "radius": radius,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_motion_blur(self, params):
        """Dispatch to gegl:motion-blur-{linear|circular|zoom} by type."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            length      = float(params.get("length", 10))
            angle       = float(params.get("angle", 0))
            blur_type   = (params.get("type") or "linear").lower()

            OP_MAP = {
                "linear":   "gegl:motion-blur-linear",
                "circular": "gegl:motion-blur-circular",
                "zoom":     "gegl:motion-blur-zoom",
            }
            op_name = OP_MAP.get(blur_type)
            if op_name is None:
                return {"status": "error",
                        "error": f"apply_motion_blur: unknown type '{blur_type}'. Valid: {sorted(OP_MAP)}"}

            if blur_type == "linear":
                props = {"length": length, "angle": angle}
            elif blur_type == "circular":
                props = {"angle": angle}
            else:  # zoom
                props = {"factor": length / 100.0}

            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, op_name, props)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "type": blur_type, "length": length, "angle": angle,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_unsharp_mask(self, params):
        """Apply gegl:unsharp-mask to a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            radius      = float(params.get("radius", 2.0))
            amount      = float(params.get("amount", 0.5))
            threshold   = float(params.get("threshold", 0.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:unsharp-mask", {
                    "std-dev":   radius,
                    "scale":     amount,
                    "threshold": threshold,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "radius": radius, "amount": amount, "threshold": threshold,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _photo_filter(self, params):
        """Warming/cooling overlay approximation.

        GIMP 3.2 lacks a dedicated gegl:photo-filter op; this tool builds
        an equivalent effect by creating a transient color layer at the
        requested density, merging it onto the target. The result matches
        Photoshop's 'Photo Filter' adjustment closely enough for color
        grading workflows.
        """
        try:
            from gi.repository import Gegl
            image_index         = int(params.get("image_index", 0))
            layer_name          = params.get("layer_name", None)
            color_str           = params.get("color", "#ffd699")
            density             = float(params.get("density", 25))
            preserve_luminosity = bool(params.get("preserve_luminosity", True))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)

            opacity = max(0.0, min(100.0, density))
            image.undo_group_start()
            try:
                overlay = Gimp.Layer.new(image, "photo-filter-overlay",
                                         drawable.get_width(), drawable.get_height(),
                                         Gimp.ImageType.RGBA_IMAGE,
                                         opacity,
                                         Gimp.LayerMode.HSL_COLOR if preserve_luminosity
                                         else Gimp.LayerMode.NORMAL)
                image.insert_layer(overlay, None, -1)
                try: offs = drawable.get_offsets()
                except Exception: offs = None
                if isinstance(offs, tuple) and len(offs) >= 3:
                    overlay.translate(int(offs[1]), int(offs[2]))
                Gimp.context_push()
                try:
                    Gimp.context_set_foreground(Gegl.Color.new(color_str))
                    Gimp.Drawable.edit_fill(overlay, Gimp.FillType.FOREGROUND)
                finally:
                    Gimp.context_pop()
                merged = image.merge_down(overlay, Gimp.MergeType.CLIP_TO_IMAGE)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success",
                "layer_name":          merged.get_name() if merged is not None else drawable.get_name(),
                "color":               color_str,
                "density":             density,
                "preserve_luminosity": preserve_luminosity,
                "note": "photo_filter is implemented via a color overlay + HSL_COLOR merge; "
                        "GIMP 3.2 has no dedicated gegl:photo-filter op.",
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _black_and_white(self, params):
        """Channel-mixed BW conversion using gegl:channel-mixer + desaturate.

        Weights are interpreted as ~percentage influence for each source
        channel on the luminance result. Default weights approximate
        Photoshop's 'Black & White' defaults.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            red         = float(params.get("red",     40))
            yellow      = float(params.get("yellow",  60))
            green       = float(params.get("green",   40))
            cyan        = float(params.get("cyan",    60))
            blue        = float(params.get("blue",    20))
            magenta     = float(params.get("magenta", 80))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            # Collapse the six-color weights into approximate RGB-channel
            # contributions. Yellow ≈ red+green, cyan ≈ green+blue,
            # magenta ≈ red+blue, so each primary gets half of its
            # corresponding secondaries as a first-order approximation.
            r_w = (red    + yellow/2 + magenta/2) / 100.0
            g_w = (green  + yellow/2 + cyan/2)    / 100.0
            b_w = (blue   + cyan/2   + magenta/2) / 100.0
            image.undo_group_start()
            try:
                # Step 1: channel-mix the luminance mapping on each channel.
                self._apply_gegl_filter(image, drawable, "gegl:channel-mixer", {
                    "rr-gain":     r_w, "rg-gain":     g_w, "rb-gain":     b_w,
                    "gr-gain":     r_w, "gg-gain":     g_w, "gb-gain":     b_w,
                    "br-gain":     r_w, "bg-gain":     g_w, "bb-gain":     b_w,
                    "preserve-luminosity": True,
                })
                # Step 2: desaturate to pure greyscale for safety.
                pdb  = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-desaturate")
                if proc is not None:
                    cfg = proc.create_config()
                    cfg.set_property("drawable",       drawable)
                    cfg.set_property("desaturate-mode", Gimp.DesaturateMode.LUMINANCE)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "red": red, "yellow": yellow, "green": green,
                "cyan": cyan, "blue": blue, "magenta": magenta,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _shadows_highlights(self, params):
        """Apply gegl:shadows-highlights for tonal rescue."""
        try:
            image_index       = int(params.get("image_index", 0))
            layer_name        = params.get("layer_name", None)
            shadow_amount     = float(params.get("shadow_amount", 50))
            highlight_amount  = float(params.get("highlight_amount", -50))
            radius            = float(params.get("radius", 30))
            color_correction  = float(params.get("color_correction", 20))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:shadows-highlights", {
                    "shadows":          shadow_amount,
                    "highlights":       highlight_amount,
                    "radius":           radius,
                    "compress":         0.0,
                    "shadows-ccorrect":    color_correction,
                    "highlights-ccorrect": color_correction,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "shadow_amount":    shadow_amount,
                "highlight_amount": highlight_amount,
                "radius":           radius,
                "color_correction": color_correction,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _exposure(self, params):
        """Apply gegl:exposure (stops-based) to a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            ev_stops    = float(params.get("ev_stops", 0.0))
            black_level = float(params.get("black_level", 0.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:exposure", {
                    "black-level": black_level,
                    "exposure":    ev_stops,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "ev_stops": ev_stops, "black_level": black_level,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _color_temperature(self, params):
        """Apply gegl:color-temperature for warm/cool grading."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            kelvin      = float(params.get("kelvin", 6500))
            tint        = float(params.get("tint", 0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:color-temperature", {
                    "original-temperature": 6500.0,
                    "intended-temperature": kelvin,
                    "tint":                 tint,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "kelvin": kelvin, "tint": tint,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _posterize(self, params):
        """Apply gimp-drawable-posterize with a given level count."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            levels      = int(params.get("levels", 4))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb  = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-posterize")
                if proc is None:
                    return {"status": "error", "error": "gimp-drawable-posterize not available"}
                cfg = proc.create_config()
                cfg.set_property("drawable", drawable)
                cfg.set_property("levels",   levels)
                proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(), "levels": levels,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_threshold(self, params):
        """Apply gimp-drawable-threshold to a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            low         = float(params.get("low", 0.5))
            high        = float(params.get("high", 1.0))
            channel     = (params.get("channel") or "value").lower()
            CHANNEL_MAP = {
                "value": Gimp.HistogramChannel.VALUE,
                "red":   Gimp.HistogramChannel.RED,
                "green": Gimp.HistogramChannel.GREEN,
                "blue":  Gimp.HistogramChannel.BLUE,
                "alpha": Gimp.HistogramChannel.ALPHA,
            }
            ch = CHANNEL_MAP.get(channel, Gimp.HistogramChannel.VALUE)
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb  = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-threshold")
                if proc is None:
                    return {"status": "error", "error": "gimp-drawable-threshold not available"}
                cfg = proc.create_config()
                cfg.set_property("drawable",       drawable)
                cfg.set_property("channel",        ch)
                cfg.set_property("low-threshold",  low)
                cfg.set_property("high-threshold", high)
                proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "layer_name": drawable.get_name(),
                "low": low, "high": high, "channel": channel,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_levels(self, params):
        """Precise manual levels via gimp-drawable-levels.

        Input/output values accept both the 0..1 native range and the 0..255
        convenience range — values > 1.0 are divided by 255 before the call.
        """
        try:
            image_index  = int(params.get("image_index", 0))
            layer_name   = params.get("layer_name", None)
            channel      = (params.get("channel") or "value").lower()
            low_input    = float(params.get("low_input", 0))
            high_input   = float(params.get("high_input", 255))
            gamma        = float(params.get("gamma", 1.0))
            low_output   = float(params.get("low_output", 0))
            high_output  = float(params.get("high_output", 255))

            def _norm(v):
                return v / 255.0 if v > 1.0 else v
            li, hi = _norm(low_input),  _norm(high_input)
            lo, ho = _norm(low_output), _norm(high_output)

            CHANNEL_MAP = {
                "value": Gimp.HistogramChannel.VALUE,
                "red":   Gimp.HistogramChannel.RED,
                "green": Gimp.HistogramChannel.GREEN,
                "blue":  Gimp.HistogramChannel.BLUE,
                "alpha": Gimp.HistogramChannel.ALPHA,
            }
            ch = CHANNEL_MAP.get(channel, Gimp.HistogramChannel.VALUE)

            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)

            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-levels")
                if proc is None:
                    return {"status": "error", "error": "gimp-drawable-levels not available"}
                cfg = proc.create_config()
                cfg.set_property("drawable",     drawable)
                cfg.set_property("channel",      ch)
                cfg.set_property("low-input",    li)
                cfg.set_property("high-input",   hi)
                cfg.set_property("clamp-input",  False)
                cfg.set_property("gamma",        gamma)
                cfg.set_property("low-output",   lo)
                cfg.set_property("high-output",  ho)
                cfg.set_property("clamp-output", False)
                proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":      "success",
                "layer_name":  drawable.get_name(),
                "channel":     channel,
                "low_input":   low_input,  "high_input":  high_input,
                "low_output":  low_output, "high_output": high_output,
                "gamma":       gamma,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_curves(self, params):
        """Adjust tonal curves."""
        try:
            PRESETS = {
                "s_curve":  [0, 0, 64, 50, 192, 210, 255, 255],
                "lighten":  [0, 0, 128, 180, 255, 255],
                "darken":   [0, 0, 128, 75, 255, 255],
                "contrast": [0, 0, 64, 40, 192, 215, 255, 255],
            }
            CHANNEL_MAP = {
                "value": Gimp.HistogramChannel.VALUE,
                "red":   Gimp.HistogramChannel.RED,
                "green": Gimp.HistogramChannel.GREEN,
                "blue":  Gimp.HistogramChannel.BLUE,
                "alpha": Gimp.HistogramChannel.ALPHA,
            }
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            preset      = params.get("preset", "s_curve")
            custom_pts  = params.get("points", None)
            channel_str = params.get("channel", "value")

            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            channel  = CHANNEL_MAP.get(channel_str.lower(), Gimp.HistogramChannel.VALUE)

            if custom_pts is not None:
                # Flatten [[in,out],...] -> [in,out,in,out,...]
                if custom_pts and isinstance(custom_pts[0], (list, tuple)):
                    flat = []
                    for pt in custom_pts:
                        flat.extend(pt)
                    control_pts = flat
                else:
                    control_pts = list(custom_pts)
            else:
                control_pts = PRESETS.get(preset, PRESETS["s_curve"])

            image.undo_group_start()
            try:
                pts_normalized = [p / 255.0 for p in control_pts]
                # set_property can't auto-convert Python list to GimpDoubleArray.
                # Try calling curves_spline as a direct method on the drawable
                # (GI exposes gimp-drawable-curves-spline as drawable.curves_spline).
                try:
                    drawable.curves_spline(channel, pts_normalized)
                except Exception:
                    # Fallback: use array.array typed buffer which GI may accept
                    import array as _arr
                    typed = _arr.array('d', pts_normalized)
                    pdb = Gimp.get_pdb()
                    proc = pdb.lookup_procedure("gimp-drawable-curves-spline")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("drawable", drawable)
                        cfg.set_property("channel",  channel)
                        cfg.set_property("points",   typed)
                        proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_brightness_contrast(self, params):
        """Adjust brightness and contrast."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            brightness  = float(params.get("brightness", 0))
            contrast    = float(params.get("contrast", 0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-brightness-contrast")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    cfg.set_property("brightness", brightness / 127.0)
                    cfg.set_property("contrast",   contrast   / 127.0)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_hue_saturation(self, params):
        """Adjust hue, saturation, lightness."""
        try:
            HUE_RANGE_MAP = {
                "all":     Gimp.HueRange.ALL,
                "red":     Gimp.HueRange.RED,
                "yellow":  Gimp.HueRange.YELLOW,
                "green":   Gimp.HueRange.GREEN,
                "cyan":    Gimp.HueRange.CYAN,
                "blue":    Gimp.HueRange.BLUE,
                "magenta": Gimp.HueRange.MAGENTA,
            }
            image_index  = int(params.get("image_index", 0))
            layer_name   = params.get("layer_name", None)
            hue          = float(params.get("hue", 0))
            saturation   = float(params.get("saturation", 0))
            lightness    = float(params.get("lightness", 0))
            color_range  = params.get("color_range", "all")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            hue_range = HUE_RANGE_MAP.get(color_range.lower(), Gimp.HueRange.ALL)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-hue-saturation")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    cfg.set_property("hue-range", hue_range)
                    cfg.set_property("hue-offset", hue)
                    cfg.set_property("lightness",  lightness)
                    cfg.set_property("saturation", saturation)
                    cfg.set_property("overlap", 0.0)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _adjust_color_balance(self, params):
        """Adjust color balance for shadows/midtones/highlights."""
        try:
            # GIMP 3.2 uses integer constants for color-range (0=shadows,1=midtones,2=highlights)
            RANGE_MAP = {
                "shadows":    0,
                "midtones":   1,
                "highlights": 2,
            }
            image_index    = int(params.get("image_index", 0))
            layer_name     = params.get("layer_name", None)
            cyan_red       = float(params.get("cyan_red", 0))
            magenta_green  = float(params.get("magenta_green", 0))
            yellow_blue    = float(params.get("yellow_blue", 0))
            range_str      = params.get("range", "midtones")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            color_range = RANGE_MAP.get(range_str.lower(), 1)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-color-balance")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable",      drawable)
                    cfg.set_property("transfer-mode", color_range)
                    cfg.set_property("cyan-red",      cyan_red)
                    cfg.set_property("magenta-green", magenta_green)
                    cfg.set_property("yellow-blue",   yellow_blue)
                    cfg.set_property("preserve-lum",  True)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _sharpen(self, params):
        """Sharpen using unsharp mask."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            amount      = float(params.get("amount", 50.0))
            radius      = float(params.get("radius", 3.0))
            threshold   = int(params.get("threshold", 0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("plug-in-unsharp-mask")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("image",     image)
                    cfg.set_property("drawable",  drawable)
                    cfg.set_property("radius",    radius)
                    cfg.set_property("amount",    amount / 100.0)
                    cfg.set_property("threshold", threshold)
                    proc.run(cfg)
                else:
                    self._apply_gegl_filter(image, drawable, "gegl:unsharp-mask", {
                        "std-dev": radius,
                        "scale":   amount / 100.0,
                        "threshold": threshold / 255.0,
                    })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _blur(self, params):
        """Gaussian blur."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            radius_x    = float(params.get("radius_x", 5.0))
            radius_y    = float(params.get("radius_y", 5.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("plug-in-gauss")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("image",    image)
                    cfg.set_property("drawable", drawable)
                    cfg.set_property("horizontal", int(radius_x * 2 + 1))
                    cfg.set_property("vertical",   int(radius_y * 2 + 1))
                    cfg.set_property("method",     0)
                    proc.run(cfg)
                else:
                    self._apply_gegl_filter(image, drawable, "gegl:gaussian-blur", {
                        "std-dev-x": radius_x,
                        "std-dev-y": radius_y,
                    })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _denoise(self, params):
        """Noise reduction."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            strength    = int(params.get("strength", 50))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:noise-reduction", {
                    "iterations": max(1, strength // 20),
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _desaturate(self, params):
        """Desaturate a layer."""
        try:
            # GIMP 3.2: LUMINOSITY was renamed to LUMINANCE
            MODE_MAP = {
                "luminosity": Gimp.DesaturateMode.LUMINANCE,
                "luminance":  Gimp.DesaturateMode.LUMINANCE,
                "luma":       Gimp.DesaturateMode.LUMA,
                "average":    Gimp.DesaturateMode.AVERAGE,
                "lightness":  Gimp.DesaturateMode.LIGHTNESS,
            }
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            mode_str    = params.get("mode", "luminosity")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            mode = MODE_MAP.get(mode_str.lower(), Gimp.DesaturateMode.LUMINANCE)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-desaturate")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    cfg.set_property("desaturate-mode", mode)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _invert_colors(self, params):
        """Invert all colors in a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-invert")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    cfg.set_property("linear", False)
                    proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 3 — Resize & Transform
    # =========================================================================

    def _scale_image(self, params):
        """Scale image to exact dimensions."""
        try:
            image_index   = int(params.get("image_index", 0))
            width         = int(params.get("width"))
            height        = int(params.get("height"))
            interpolation = params.get("interpolation", "cubic")
            image  = self._get_image(image_index)
            self._interp_from_string(interpolation)
            image.undo_group_start()
            try:
                image.scale(width, height)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "width": width, "height": height}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _scale_to_fit(self, params):
        """Scale image to fit within a bounding box preserving aspect ratio."""
        try:
            image_index   = int(params.get("image_index", 0))
            max_width     = int(params.get("max_width"))
            max_height    = int(params.get("max_height"))
            interpolation = params.get("interpolation", "cubic")
            image  = self._get_image(image_index)
            self._interp_from_string(interpolation)
            src_w  = image.get_width()
            src_h  = image.get_height()
            aspect = src_w / src_h
            max_aspect = max_width / max_height
            if aspect > max_aspect:
                new_w = max_width
                new_h = max(1, int(max_width / aspect))
            else:
                new_h = max_height
                new_w = max(1, int(max_height * aspect))
            image.undo_group_start()
            try:
                image.scale(new_w, new_h)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "width": new_w, "height": new_h}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _crop_to_selection(self, params):
        """Crop image to selection bounds."""
        try:
            image_index = int(params.get("image_index", 0))
            autocrop    = bool(params.get("autocrop", False))
            image = self._get_image(image_index)
            image.undo_group_start()
            try:
                if autocrop:
                    pdb = Gimp.get_pdb()
                    proc = pdb.lookup_procedure("gimp-image-autocrop")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("image", image)
                        proc.run(cfg)
                else:
                    _ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
                    if non_empty:
                        image.crop(x2 - x1, y2 - y1, x1, y1)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _crop_to_rect(self, params):
        """Crop image to explicit rectangle."""
        try:
            image_index = int(params.get("image_index", 0))
            x      = int(params.get("x", 0))
            y      = int(params.get("y", 0))
            width  = int(params.get("width"))
            height = int(params.get("height"))
            image = self._get_image(image_index)
            image.undo_group_start()
            try:
                image.crop(width, height, x, y)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "x": x, "y": y, "width": width, "height": height}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _rotate_image(self, params):
        """Rotate image by angle."""
        try:
            image_index = int(params.get("image_index", 0))
            angle       = float(params.get("angle", 90))
            image = self._get_image(image_index)
            image.undo_group_start()
            try:
                rot_map = {
                    90.0:  Gimp.RotationType.DEGREES90,
                    180.0: Gimp.RotationType.DEGREES180,
                    270.0: Gimp.RotationType.DEGREES270,
                    -90.0: Gimp.RotationType.DEGREES270,
                }
                if angle in rot_map:
                    image.rotate(rot_map[angle])
                else:
                    import math
                    rad = math.radians(angle)
                    for layer in image.get_layers():
                        pdb = Gimp.get_pdb()
                        proc = pdb.lookup_procedure("gimp-item-transform-rotate-default")
                        if proc:
                            cfg = proc.create_config()
                            cfg.set_property("item",      layer)
                            cfg.set_property("angle",     rad)
                            cfg.set_property("auto-center", True)
                            cfg.set_property("center-x",  0)
                            cfg.set_property("center-y",  0)
                            proc.run(cfg)
                    image.flatten()
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "angle": angle}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _flip_image(self, params):
        """Flip image horizontally or vertically."""
        try:
            image_index = int(params.get("image_index", 0))
            direction   = params.get("direction", "horizontal").lower()
            image = self._get_image(image_index)
            orient = Gimp.OrientationType.HORIZONTAL if direction == "horizontal" else Gimp.OrientationType.VERTICAL
            image.undo_group_start()
            try:
                image.flip(orient)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "direction": direction}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _resize_canvas(self, params):
        """Resize canvas without scaling content."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            new_w  = int(params.get("width"))
            new_h  = int(params.get("height"))
            anchor = params.get("anchor", "center").lower()
            fill   = params.get("fill", "transparent")
            image  = self._get_image(image_index)
            src_w  = image.get_width()
            src_h  = image.get_height()
            # Compute offset based on anchor
            dx = (new_w - src_w) // 2
            dy = (new_h - src_h) // 2
            anchor_offsets = {
                "center":       (dx,         dy),
                "top-left":     (0,          0),
                "top":          (dx,         0),
                "top-right":    (new_w - src_w, 0),
                "left":         (0,          dy),
                "right":        (new_w - src_w, dy),
                "bottom-left":  (0,          new_h - src_h),
                "bottom":       (dx,         new_h - src_h),
                "bottom-right": (new_w - src_w, new_h - src_h),
            }
            off_x, off_y = anchor_offsets.get(anchor, (dx, dy))
            image.undo_group_start()
            try:
                image.resize(new_w, new_h, off_x, off_y)
                if fill.lower() != "transparent":
                    Gimp.context_push()
                    try:
                        bg = Gegl.Color.new(fill)
                        Gimp.context_set_background(bg)
                        image.flatten()
                    finally:
                        Gimp.context_pop()
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "width": new_w, "height": new_h, "offset_x": off_x, "offset_y": off_y}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 4 — Selections
    # =========================================================================

    def _select_rectangle(self, params):
        """Create a rectangular selection."""
        try:
            image_index = int(params.get("image_index", 0))
            x       = int(params.get("x", 0))
            y       = int(params.get("y", 0))
            width   = int(params.get("width"))
            height  = int(params.get("height"))
            operation = params.get("operation", "replace")
            feather   = float(params.get("feather", 0))
            image = self._get_image(image_index)
            op = self._channel_ops_from_string(operation)
            image.select_rectangle(op, x, y, width, height)
            if feather > 0:
                Gimp.Selection.feather(image, feather)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _select_ellipse(self, params):
        """Create an elliptical selection."""
        try:
            image_index = int(params.get("image_index", 0))
            x       = int(params.get("x", 0))
            y       = int(params.get("y", 0))
            width   = int(params.get("width"))
            height  = int(params.get("height"))
            operation = params.get("operation", "replace")
            feather   = float(params.get("feather", 0))
            image = self._get_image(image_index)
            op = self._channel_ops_from_string(operation)
            image.select_ellipse(op, x, y, width, height)
            if feather > 0:
                Gimp.Selection.feather(image, feather)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _select_by_color(self, params):
        """Select by color similarity."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            color_str   = params.get("color", "white")
            threshold   = int(params.get("threshold", 15))
            operation   = params.get("operation", "replace")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            op = self._channel_ops_from_string(operation)
            color = Gegl.Color.new(color_str)
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-by-color-select")
            if proc:
                cfg = proc.create_config()
                cfg.set_property("drawable",    drawable)
                cfg.set_property("color",       color)
                cfg.set_property("threshold",   threshold)
                cfg.set_property("operation",   op)
                cfg.set_property("antialias",   True)
                cfg.set_property("feather",     False)
                cfg.set_property("feather-radius", 0.0)
                cfg.set_property("sample-merged", False)
                proc.run(cfg)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _select_all(self, params):
        """Select entire canvas."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            Gimp.Selection.all(image)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _select_none(self, params):
        """Remove all selections."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            Gimp.Selection.none(image)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _invert_selection(self, params):
        """Invert selection."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            Gimp.Selection.invert(image)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _modify_selection(self, params):
        """Grow/shrink/feather/border/sharpen selection."""
        try:
            image_index = int(params.get("image_index", 0))
            operation   = params.get("operation", "grow").lower()
            amount      = float(params.get("amount", 0))
            image = self._get_image(image_index)
            OP_MAP = {
                "grow":    Gimp.Selection.grow,
                "shrink":  Gimp.Selection.shrink,
                "feather": Gimp.Selection.feather,
                "border":  Gimp.Selection.border,
                "sharpen": Gimp.Selection.sharpen,
            }
            fn = OP_MAP.get(operation)
            if fn is None:
                return {"status": "error", "error": f"Unknown selection operation: {operation}"}
            if operation == "sharpen":
                fn(image)
            else:
                fn(image, amount)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _fuzzy_select(self, params):
        """Fuzzy-select the contiguous-color region at a pixel.

        Unlike select_by_color (which grabs all regions of the sampled color),
        fuzzy_select grabs only the one region enclosing (x, y). Mirrors the
        bucket-fill / magic-wand primitive.
        """
        try:
            image_index    = int(params.get("image_index", 0))
            layer_name     = params.get("layer_name", None)
            x              = float(params.get("x", 0))
            y              = float(params.get("y", 0))
            threshold      = float(params.get("threshold", 15.0))
            sample_merged  = bool(params.get("sample_merged", False))
            operation      = (params.get("operation") or "replace").lower()
            antialias      = bool(params.get("antialias", True))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            op = self._channel_ops_from_string(operation)

            Gimp.context_push()
            try:
                try: Gimp.context_set_sample_threshold(threshold / 255.0 if threshold > 1 else threshold)
                except Exception: pass
                try: Gimp.context_set_sample_merged(sample_merged)
                except Exception: pass
                try: Gimp.context_set_antialias(antialias)
                except Exception: pass
                image.select_contiguous_color(op, drawable, x, y)
            finally:
                Gimp.context_pop()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":        "success",
                "layer_name":    drawable.get_name(),
                "x":             x,
                "y":             y,
                "threshold":     threshold,
                "sample_merged": sample_merged,
                "antialias":     antialias,
                "operation":     operation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _alpha_to_selection(self, params):
        """Load a layer's alpha channel into the selection via image.select_item."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            operation   = (params.get("operation") or "replace").lower()
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            op = self._channel_ops_from_string(operation)
            image.select_item(op, drawable)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": drawable.get_name(),
                "operation":  operation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 5 — Layer Operations
    # =========================================================================

    # Map user-friendly blend-mode strings to Gimp.LayerMode enum names.
    # Resolution is defensive: enums missing from a given 3.2 build fall back
    # to NORMAL rather than raising, so the table is safe across builds.
    _BLEND_MODE_ENUM_MAP = {
        "NORMAL":         "NORMAL",
        "DISSOLVE":       "DISSOLVE",
        "MULTIPLY":       "MULTIPLY",
        "SCREEN":         "SCREEN",
        "OVERLAY":        "OVERLAY",
        "DIFFERENCE":     "DIFFERENCE",
        "ADDITION":       "ADDITION",
        "SUBTRACT":       "SUBTRACT",
        "DIVIDE":         "DIVIDE",
        "DARKEN":         "DARKEN_ONLY",
        "DARKEN_ONLY":    "DARKEN_ONLY",
        "LIGHTEN":        "LIGHTEN_ONLY",
        "LIGHTEN_ONLY":   "LIGHTEN_ONLY",
        "DODGE":          "DODGE",
        "BURN":           "BURN",
        "HARD_LIGHT":     "HARDLIGHT",
        "HARDLIGHT":      "HARDLIGHT",
        "SOFT_LIGHT":     "SOFTLIGHT",
        "SOFTLIGHT":      "SOFTLIGHT",
        "GRAIN_MERGE":    "GRAIN_MERGE",
        "GRAIN_EXTRACT":  "GRAIN_EXTRACT",
        "VIVID_LIGHT":    "VIVID_LIGHT",
        "LINEAR_LIGHT":   "LINEAR_LIGHT",
        "PIN_LIGHT":      "PIN_LIGHT",
        "HARD_MIX":       "HARD_MIX",
        "LINEAR_BURN":    "LINEAR_BURN",
        "EXCLUSION":      "EXCLUSION",
        "MERGE":          "MERGE",
        "SPLIT":          "SPLIT",
        "COLOR_ERASE":    "COLOR_ERASE",
        "ERASE":          "ERASE",
        "REPLACE":        "REPLACE",
        "ANTI_ERASE":     "ANTI_ERASE",
        "BEHIND":         "BEHIND",
        "PASS_THROUGH":   "PASS_THROUGH",
        # HSV / HSL / LCH family — friendly aliases first, explicit names after
        "HUE":            "HSV_HUE",
        "SATURATION":     "HSV_SATURATION",
        "COLOR":          "HSL_COLOR",
        "LUMINOSITY":     "HSV_VALUE",
        "HSV_HUE":        "HSV_HUE",
        "HSV_SATURATION": "HSV_SATURATION",
        "HSV_VALUE":      "HSV_VALUE",
        "HSL_COLOR":      "HSL_COLOR",
        "LCH_HUE":        "LCH_HUE",
        "LCH_CHROMA":     "LCH_CHROMA",
        "LCH_COLOR":      "LCH_COLOR",
        "LCH_LIGHTNESS":  "LCH_LIGHTNESS",
    }

    def _blend_mode_from_string(self, mode_str):
        """Resolve a blend-mode string to a Gimp.LayerMode value."""
        if not mode_str:
            return Gimp.LayerMode.NORMAL
        enum_name = self._BLEND_MODE_ENUM_MAP.get(mode_str.upper())
        if enum_name is None:
            return Gimp.LayerMode.NORMAL
        return getattr(Gimp.LayerMode, enum_name, Gimp.LayerMode.NORMAL)

    def _create_layer(self, params):
        """Create and insert a new layer."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            name        = params.get("name", "New Layer")
            opacity     = float(params.get("opacity", 100))
            blend_mode  = params.get("blend_mode", "NORMAL")
            position    = int(params.get("position", -1))
            fill        = params.get("fill", "transparent")
            image = self._get_image(image_index)
            width  = int(params.get("width")  or image.get_width())
            height = int(params.get("height") or image.get_height())
            mode   = self._blend_mode_from_string(blend_mode)
            # Determine layer type
            base_type  = image.get_base_type()
            layer_type = Gimp.ImageType.RGBA_IMAGE if base_type == Gimp.ImageBaseType.RGB else Gimp.ImageType.GRAYA_IMAGE
            image.undo_group_start()
            try:
                layer = Gimp.Layer.new(image, name, width, height, layer_type, opacity, mode)
                image.insert_layer(layer, None, position)
                Gimp.context_push()
                try:
                    if fill.lower() == "transparent":
                        layer.add_alpha()
                        Gimp.Drawable.edit_fill(layer, Gimp.FillType.TRANSPARENT)
                    else:
                        bg = Gegl.Color.new(fill)
                        Gimp.context_set_background(bg)
                        Gimp.Drawable.edit_fill(layer, Gimp.FillType.BACKGROUND)
                finally:
                    Gimp.context_pop()
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {
                "status": "success",
                "results": {
                    "layer_name": layer.get_name(),
                    "layer_id":   layer.get_id(),
                    "width":      width,
                    "height":     height,
                    "position":   position,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _duplicate_layer(self, params):
        """Duplicate a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image    = self._get_image(image_index)
            layer    = self._resolve_layer(image, layer_name, None)
            layers   = image.get_layers()
            position = layers.index(layer) if layer in layers else 0
            image.undo_group_start()
            try:
                new_layer = layer.copy()
                image.insert_layer(new_layer, None, position)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"layer_name": new_layer.get_name(), "layer_id": new_layer.get_id()}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _delete_layer(self, params):
        """Delete a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            layer_index = params.get("layer_index", None)
            if layer_index is not None:
                layer_index = int(layer_index)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, layer_index)
            image.undo_group_start()
            try:
                image.remove_layer(layer)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _rename_layer(self, params):
        """Rename a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            old_name    = params.get("old_name", None)
            layer_index = params.get("layer_index", None)
            new_name    = params.get("new_name", "")
            if layer_index is not None:
                layer_index = int(layer_index)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, old_name, layer_index)
            prev_name = layer.get_name()
            layer.set_name(new_name)
            Gimp.displays_flush()
            return {"status": "success", "results": {"old_name": prev_name, "new_name": new_name}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_layer_properties(self, params):
        """Set layer opacity, blend mode, and/or visibility."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            layer_index = params.get("layer_index", None)
            opacity     = params.get("opacity", None)
            blend_mode  = params.get("blend_mode", None)
            visible     = params.get("visible", None)
            if layer_index is not None:
                layer_index = int(layer_index)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, layer_index)
            image.undo_group_start()
            try:
                if opacity is not None:
                    layer.set_opacity(float(opacity))
                if blend_mode is not None:
                    layer.set_mode(self._blend_mode_from_string(blend_mode))
                if visible is not None:
                    layer.set_visible(bool(visible))
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _reorder_layer(self, params):
        """Move a layer to a new stack position."""
        try:
            image_index  = int(params.get("image_index", 0))
            layer_name   = params.get("layer_name", None)
            layer_index  = params.get("layer_index", None)
            new_position = int(params.get("new_position", 0))
            if layer_index is not None:
                layer_index = int(layer_index)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, layer_index)
            image.undo_group_start()
            try:
                image.reorder_item(layer, None, new_position)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    _ADD_MASK_TYPE_MAP = {
        "white":           "WHITE",
        "black":           "BLACK",
        "alpha":           "ALPHA",
        "alpha-transfer":  "ALPHA_TRANSFER",
        "alpha_transfer":  "ALPHA_TRANSFER",
        "selection":       "SELECTION",
        "copy":            "COPY",
        "channel":         "CHANNEL",
    }

    def _threshold_layer_mask(self, params):
        """Threshold a layer's mask in place via gimp-drawable-threshold."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            low         = float(params.get("low", 0.5))
            high        = float(params.get("high", 1.0))
            channel     = (params.get("channel") or "value").lower()

            CHANNEL_MAP = {
                "value": Gimp.HistogramChannel.VALUE,
                "red":   Gimp.HistogramChannel.RED,
                "green": Gimp.HistogramChannel.GREEN,
                "blue":  Gimp.HistogramChannel.BLUE,
                "alpha": Gimp.HistogramChannel.ALPHA,
            }
            ch = CHANNEL_MAP.get(channel, Gimp.HistogramChannel.VALUE)

            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            mask  = layer.get_mask()
            if mask is None:
                return {"status": "error",
                        "error": f"layer '{layer.get_name()}' has no mask"}

            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-threshold")
                if proc is None:
                    return {"status": "error", "error": "gimp-drawable-threshold not available"}
                cfg = proc.create_config()
                cfg.set_property("drawable",       mask)
                cfg.set_property("channel",        ch)
                cfg.set_property("low-threshold",  low)
                cfg.set_property("high-threshold", high)
                proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": layer.get_name(),
                "low":        low,
                "high":       high,
                "channel":    channel,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _remove_layer_mask(self, params):
        """Apply or discard a layer's mask."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            action      = (params.get("action") or "apply").lower()

            ACTION_MAP = {"apply": "APPLY", "discard": "DISCARD"}
            enum_name = ACTION_MAP.get(action)
            if enum_name is None:
                return {"status": "error",
                        "error": f"remove_layer_mask: unknown action '{action}'. Valid: apply, discard"}
            mode = getattr(Gimp.MaskApplyMode, enum_name, None)
            if mode is None:
                return {"status": "error",
                        "error": f"Gimp.MaskApplyMode.{enum_name} not available in this build"}

            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            if layer.get_mask() is None:
                return {"status": "error",
                        "error": f"layer '{layer.get_name()}' has no mask"}

            image.undo_group_start()
            try:
                layer.remove_mask(mode)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": layer.get_name(),
                "action":     action,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _add_layer_mask(self, params):
        """Create and attach a layer mask of the requested type."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            mask_type   = (params.get("mask_type") or "white").lower()

            enum_name = self._ADD_MASK_TYPE_MAP.get(mask_type)
            if enum_name is None:
                return {"status": "error",
                        "error": f"add_layer_mask: unknown mask_type '{mask_type}'. "
                                 f"Valid: {sorted(self._ADD_MASK_TYPE_MAP)}"}
            mt = getattr(Gimp.AddMaskType, enum_name, None)
            if mt is None:
                return {"status": "error",
                        "error": f"add_layer_mask: Gimp.AddMaskType.{enum_name} not available in this build"}

            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            if layer.get_mask() is not None:
                return {"status": "error",
                        "error": f"layer '{layer.get_name()}' already has a mask"}

            image.undo_group_start()
            try:
                mask = layer.create_mask(mt)
                layer.add_mask(mask)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": layer.get_name(),
                "mask_id":    mask.get_id() if mask is not None else None,
                "mask_type":  mask_type,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _transform_layer(self, params):
        """Scale and/or translate a single layer (distinct from scale_image).

        Scale pair (scale_width + scale_height) and offset pair (offset_x +
        offset_y) are independent — pass only the pair you want applied.
        """
        try:
            image_index  = int(params.get("image_index", 0))
            layer_name   = params.get("layer_name", None)
            scale_w      = params.get("scale_width")
            scale_h      = params.get("scale_height")
            offset_x     = params.get("offset_x")
            offset_y     = params.get("offset_y")
            local_origin = bool(params.get("local_origin", True))

            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)

            image.undo_group_start()
            try:
                if scale_w is not None and scale_h is not None:
                    layer.scale(int(scale_w), int(scale_h), local_origin)
                if offset_x is not None or offset_y is not None:
                    dx = int(offset_x) if offset_x is not None else 0
                    dy = int(offset_y) if offset_y is not None else 0
                    layer.translate(dx, dy)
            finally:
                image.undo_group_end()

            Gimp.displays_flush()
            result = {
                "status":     "success",
                "layer_name": layer.get_name(),
                "width":      layer.get_width(),
                "height":     layer.get_height(),
            }
            try:
                offs = layer.get_offsets()
                # get_offsets returns (ok, x, y) in some bindings, (x, y) in others
                if isinstance(offs, tuple) and len(offs) == 3:
                    result["offset_x"], result["offset_y"] = int(offs[1]), int(offs[2])
                elif isinstance(offs, tuple) and len(offs) == 2:
                    result["offset_x"], result["offset_y"] = int(offs[0]), int(offs[1])
            except Exception:
                pass
            return {"status": "success", "results": result}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _flatten_image(self, params):
        """Flatten all layers."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            image.undo_group_start()
            try:
                image.flatten()
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _merge_visible_layers(self, params):
        """Merge visible layers."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            image.undo_group_start()
            try:
                merged = image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"layer_name": merged.get_name(), "layer_id": merged.get_id()}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_layers(self, params):
        """List all layers with properties."""
        try:
            image  = self._get_image(int(params.get("image_index", 0)))
            layers = image.get_layers()
            layer_list = []
            for i, layer in enumerate(layers):
                try:
                    layer_list.append({
                        "index":      i,
                        "name":       layer.get_name(),
                        "id":         layer.get_id(),
                        "visible":    layer.get_visible(),
                        "opacity":    layer.get_opacity(),
                        "blend_mode": str(layer.get_mode()),
                        "width":      layer.get_width(),
                        "height":     layer.get_height(),
                        "has_alpha":  layer.has_alpha(),
                        "offsets":    list(layer.get_offsets()),
                    })
                except Exception as ex:
                    layer_list.append({"index": i, "error": str(ex)})
            return {"status": "success", "results": {"layers": layer_list, "count": len(layer_list)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 6 — Color & Paint
    # =========================================================================

    def _fill_layer(self, params):
        """Fill entire layer with color."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            color_str   = params.get("color", "white")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                Gimp.Selection.all(image)
                fg = Gegl.Color.new(color_str)
                Gimp.context_set_foreground(fg)
                Gimp.Drawable.edit_fill(drawable, Gimp.FillType.FOREGROUND)
                Gimp.Selection.none(image)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _fill_selection(self, params):
        """Fill current selection with color or transparency."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            fill_type   = (params.get("fill_type") or "foreground").lower()
            color_str   = params.get("color", "white")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                if fill_type == "transparent":
                    # Ensure layer has alpha channel before deleting pixels
                    if not drawable.has_alpha():
                        drawable.add_alpha()
                    Gimp.Drawable.edit_clear(drawable)
                elif fill_type == "background":
                    Gimp.Drawable.edit_fill(drawable, Gimp.FillType.BACKGROUND)
                elif fill_type == "pattern":
                    Gimp.Drawable.edit_fill(drawable, Gimp.FillType.PATTERN)
                else:
                    # foreground (default) or explicit color
                    fg = Gegl.Color.new(color_str if fill_type not in ("foreground",) else color_str)
                    Gimp.context_set_foreground(fg)
                    Gimp.Drawable.edit_fill(drawable, Gimp.FillType.FOREGROUND)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_colors(self, params):
        """Set foreground and/or background color."""
        try:
            from gi.repository import Gegl
            fg_str = params.get("foreground", None)
            bg_str = params.get("background", None)
            if fg_str is not None:
                Gimp.context_set_foreground(Gegl.Color.new(fg_str))
            if bg_str is not None:
                Gimp.context_set_background(Gegl.Color.new(bg_str))
            return {"status": "success", "results": {"foreground": fg_str, "background": bg_str}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _draw_line(self, params):
        """Draw a straight line."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 0))
            y2 = float(params.get("y2", 0))
            color_str  = params.get("color", None)
            line_width = float(params.get("width", 2.0))
            tool       = params.get("tool", "pencil").lower()
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                if color_str:
                    Gimp.context_set_foreground(Gegl.Color.new(color_str))
                Gimp.context_set_brush_size(line_width)
                Gimp.context_set_opacity(100.0)
                coords = [x1, y1, x2, y2]
                if tool == "paintbrush":
                    Gimp.paintbrush_default(drawable, coords)
                else:
                    Gimp.pencil(drawable, coords)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _draw_rectangle(self, params):
        """Draw a rectangle outline."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x          = int(params.get("x", 0))
            y          = int(params.get("y", 0))
            width      = int(params.get("width"))
            height     = int(params.get("height"))
            color_str  = params.get("color", None)
            line_width = float(params.get("line_width", 2.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                if color_str:
                    Gimp.context_set_foreground(Gegl.Color.new(color_str))
                Gimp.context_set_stroke_method(Gimp.StrokeMethod.LINE)
                Gimp.context_set_line_width(line_width)
                Gimp.context_set_opacity(100.0)
                image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, width, height)
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-edit-stroke-selection")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    proc.run(cfg)
                Gimp.Selection.none(image)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _draw_ellipse(self, params):
        """Draw an ellipse outline."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x          = int(params.get("x", 0))
            y          = int(params.get("y", 0))
            width      = int(params.get("width"))
            height     = int(params.get("height"))
            color_str  = params.get("color", None)
            line_width = float(params.get("line_width", 2.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                if color_str:
                    Gimp.context_set_foreground(Gegl.Color.new(color_str))
                Gimp.context_set_stroke_method(Gimp.StrokeMethod.LINE)
                Gimp.context_set_line_width(line_width)
                Gimp.context_set_opacity(100.0)
                image.select_ellipse(Gimp.ChannelOps.REPLACE, x, y, width, height)
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-drawable-edit-stroke-selection")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("drawable", drawable)
                    proc.run(cfg)
                Gimp.Selection.none(image)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _fill_rectangle(self, params):
        """Fill a rectangular region with color."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x       = int(params.get("x", 0))
            y       = int(params.get("y", 0))
            width   = int(params.get("width"))
            height  = int(params.get("height"))
            color_str = params.get("color", "white")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, width, height)
                Gimp.context_set_foreground(Gegl.Color.new(color_str))
                Gimp.Drawable.edit_fill(drawable, Gimp.FillType.FOREGROUND)
                Gimp.Selection.none(image)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _fill_ellipse(self, params):
        """Fill an elliptical region with color."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x       = int(params.get("x", 0))
            y       = int(params.get("y", 0))
            width   = int(params.get("width"))
            height  = int(params.get("height"))
            color_str = params.get("color", "white")
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            Gimp.context_push()
            try:
                image.select_ellipse(Gimp.ChannelOps.REPLACE, x, y, width, height)
                Gimp.context_set_foreground(Gegl.Color.new(color_str))
                Gimp.Drawable.edit_fill(drawable, Gimp.FillType.FOREGROUND)
                Gimp.Selection.none(image)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _gradient_fill(self, params):
        """Fill with a gradient using GEGL (gimp-blend was removed in GIMP 3)."""
        try:
            from gi.repository import Gegl
            image_index   = int(params.get("image_index", 0))
            layer_name    = params.get("layer_name", None)
            color1        = params.get("color1", "black")
            color2        = params.get("color2", "white")
            gradient_type = params.get("gradient_type", "linear").lower()
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            w = image.get_width()
            h = image.get_height()
            x1 = float(params.get("x1") or params.get("start_x") or 0)
            y1 = float(params.get("y1") or params.get("start_y") or 0)
            x2 = float(params.get("x2") or params.get("end_x") or w)
            y2 = float(params.get("y2") or params.get("end_y") or h)

            image.undo_group_start()
            Gimp.context_push()
            try:
                Gimp.context_set_foreground(Gegl.Color.new(color1))
                Gimp.context_set_background(Gegl.Color.new(color2))

                Gegl.init(None)
                shadow_buf = drawable.get_shadow_buffer()
                graph = Gegl.Node()

                op_name = "gegl:radial-gradient" if gradient_type == "radial" else "gegl:linear-gradient"
                grad_node = graph.create_child(op_name)
                try:
                    grad_node.set_property("start-color", Gegl.Color.new(color1))
                    grad_node.set_property("end-color",   Gegl.Color.new(color2))
                except Exception:
                    pass
                if w > 0 and h > 0:
                    try:
                        grad_node.set_property("x0", x1 / w)
                        grad_node.set_property("y0", y1 / h)
                        grad_node.set_property("x1", x2 / w)
                        grad_node.set_property("y1", y2 / h)
                    except Exception:
                        pass

                out_node = graph.create_child("gegl:write-buffer")
                out_node.set_property("buffer", shadow_buf)
                grad_node.link(out_node)
                out_node.process()

                shadow_buf.flush()
                drawable.merge_shadow(True)
                drawable.update(0, 0, w, h)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # Map tool name → (PDB procedure name). All paint-tool defaults take just
    # (drawable, strokes) in GIMP 3.2 — dynamics/brush/color come from context.
    _PAINT_TOOL_PDB = {
        "paintbrush":  "gimp-paintbrush-default",
        "pencil":      "gimp-pencil",
        "airbrush":    "gimp-airbrush-default",
        "smudge":      "gimp-smudge-default",
        "eraser":      "gimp-eraser-default",
        "dodge":       "gimp-dodgeburn-default",
        "burn":        "gimp-dodgeburn-default",
        "convolve":    "gimp-convolve-default",
        "ink":         "gimp-ink",
        "mypaint":     "gimp-mypaint-brush-default",
    }

    def _apply_paint_context(self, brush, size, hardness, opacity, dynamics, color, mode, dodgeburn_type):
        """Push paint context settings. Each setter is best-effort; unknown props skip."""
        from gi.repository import Gegl
        if brush is not None:
            try:
                brush_obj = Gimp.Brush.get_by_name(brush)
                if brush_obj is not None:
                    Gimp.context_set_brush(brush_obj)
            except Exception:
                pass
        if size is not None:
            try: Gimp.context_set_brush_size(float(size))
            except Exception: pass
        if hardness is not None:
            try: Gimp.context_set_brush_hardness(float(hardness))
            except Exception: pass
        if opacity is not None:
            try: Gimp.context_set_opacity(float(opacity))
            except Exception: pass
        if dynamics is not None:
            try: Gimp.context_set_dynamics_name(dynamics)
            except Exception: pass
        if color is not None:
            try: Gimp.context_set_foreground(Gegl.Color.new(color))
            except Exception: pass
        if mode is not None:
            try: Gimp.context_set_paint_mode(self._blend_mode_from_string(mode))
            except Exception: pass
        if dodgeburn_type is not None:
            for setter_name in ("context_set_dodge_burn_type", "context_set_dodgeburn_type"):
                setter = getattr(Gimp, setter_name, None)
                if setter is None:
                    continue
                try:
                    dbtype = (Gimp.DodgeBurnType.DODGE if dodgeburn_type == "dodge"
                              else Gimp.DodgeBurnType.BURN)
                    setter(dbtype)
                    break
                except Exception:
                    continue

    def _paint_stroke(self, params):
        """Unified paint-tool stroke dispatcher.

        Wraps gimp-paintbrush-default / pencil / airbrush / smudge / eraser /
        dodgeburn / convolve / ink / mypaint via (drawable, strokes) PDB calls.
        Context (brush, size, hardness, opacity, dynamics, color, mode) is
        pushed before the call and popped in finally.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            tool        = (params.get("tool") or "paintbrush").lower()
            raw_strokes = params.get("strokes") or []
            brush       = params.get("brush")
            size        = params.get("size")
            hardness    = params.get("hardness")
            opacity     = params.get("opacity")
            dynamics    = params.get("dynamics")
            color       = params.get("color")
            mode        = params.get("mode")

            if not isinstance(raw_strokes, list) or not raw_strokes:
                return {"status": "error",
                        "error": "paint_stroke: 'strokes' must be a non-empty list [x1,y1,x2,y2,...]"}
            if len(raw_strokes) % 2 != 0:
                return {"status": "error",
                        "error": "paint_stroke: 'strokes' length must be even (x,y pairs)"}
            try:
                strokes = [float(v) for v in raw_strokes]
            except (TypeError, ValueError) as conv_err:
                return {"status": "error",
                        "error": f"paint_stroke: non-numeric stroke value ({conv_err})"}

            pdb_name = self._PAINT_TOOL_PDB.get(tool)
            if pdb_name is None:
                return {"status": "error",
                        "error": f"paint_stroke: unknown tool '{tool}'. Valid: {sorted(self._PAINT_TOOL_PDB)}"}

            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)

            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure(pdb_name)
            if proc is None:
                return {"status": "error",
                        "error": f"paint_stroke: PDB procedure not available in this GIMP build: {pdb_name}"}

            dodgeburn_type = tool if tool in ("dodge", "burn") else None

            image.undo_group_start()
            Gimp.context_push()
            try:
                self._apply_paint_context(brush, size, hardness, opacity,
                                          dynamics, color, mode, dodgeburn_type)
                if tool == "ink" and size is not None:
                    try: Gimp.context_set_ink_size(float(size))
                    except Exception: pass

                cfg = proc.create_config()
                cfg.set_property("drawable", drawable)
                cfg.set_property("strokes",  strokes)
                proc.run(cfg)
            finally:
                Gimp.context_pop()
                image.undo_group_end()

            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "tool":         tool,
                "pdb":          pdb_name,
                "stroke_count": len(strokes) // 2,
                "layer_name":   drawable.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 7 — Text
    # =========================================================================

    def _resolve_font(self, name):
        """Resolve a font name to a Gimp.Font."""
        if not (hasattr(Gimp, "Font") and hasattr(Gimp.Font, "get_by_name")):
            return None

        font_obj = Gimp.Font.get_by_name(name)
        if font_obj is not None:
            return font_obj

        # GIMP 3.2 dropped GIMP 2.x aliases; e.g. "Sans" no longer resolves,
        # the 3.2 equivalent is "Sans-serif".
        for alias in (name + "-serif", name + " Regular",
                      name.replace(" ", "-"),
                      "Sans-serif", "Serif", "Monospace"):
            font_obj = Gimp.Font.get_by_name(alias)
            if font_obj is not None:
                return font_obj

        raw = Gimp.fonts_get_list("")
        flist = list(raw[1]) if isinstance(raw, tuple) and len(raw) > 1 else list(raw)
        return flist[0] if flist else None

    def _create_text_layer_native(self, image, text, font_obj, size, x, y, color_str):
        """Create a text layer via Gimp.TextLayer.new."""
        from gi.repository import Gegl
        if not hasattr(Gimp, "TextLayer"):
            return None

        try:
            tl = Gimp.TextLayer.new(image, text, font_obj, float(size), Gimp.Unit.pixel())
        except Exception:
            return None
        if tl is None:
            return None

        try:
            image.insert_layer(tl, None, 0)
        except Exception:
            return None

        # Layer is now in the image; swallow offset/color failures so the
        # caller does not fall through to the PDB fallback and insert a
        # second layer.
        try:
            tl.set_offsets(x, y)
        except Exception:
            pass
        try:
            pdb   = Gimp.get_pdb()
            cproc = pdb.lookup_procedure("gimp-text-layer-set-color")
            if cproc:
                ccfg = cproc.create_config()
                ccfg.set_property("layer", tl)
                ccfg.set_property("color", Gegl.Color.new(color_str))
                cproc.run(ccfg)
        except Exception:
            pass
        return tl

    def _create_text_layer_pdb(self, image, text, font_obj, size, x, y):
        """Create a text layer via the gimp-text-font PDB procedure."""
        proc = Gimp.get_pdb().lookup_procedure("gimp-text-font")
        if proc is None:
            return
        cfg = proc.create_config()
        cfg.set_property("image",     image)
        cfg.set_property("drawable",  None)
        cfg.set_property("x",         float(x))
        cfg.set_property("y",         float(y))
        cfg.set_property("text",      text)
        cfg.set_property("border",    0)
        cfg.set_property("antialias", True)
        cfg.set_property("size",      float(size))
        cfg.set_property("font",      font_obj)
        proc.run(cfg)

    def _find_new_layer(self, image, before_ids):
        """Return the first layer whose id is not in before_ids."""
        for lyr in image.get_layers():
            if lyr.get_id() not in before_ids:
                return lyr
        return None

    def _add_text(self, params):
        """Add a text layer."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            text_str    = params.get("text", "")
            x           = int(params.get("x", 0))
            y           = int(params.get("y", 0))
            font        = params.get("font", "Sans")
            size        = int(params.get("size", 24))
            color_str   = params.get("color", "black")

            image      = self._get_image(image_index)
            before_ids = {lyr.get_id() for lyr in image.get_layers()}
            text_layer = None

            image.undo_group_start()
            Gimp.context_push()
            try:
                Gimp.context_set_foreground(Gegl.Color.new(color_str))
                font_obj = self._resolve_font(font)
                if font_obj is not None:
                    text_layer = self._create_text_layer_native(
                        image, text_str, font_obj, size, x, y, color_str)
                    if text_layer is None:
                        self._create_text_layer_pdb(
                            image, text_str, font_obj, size, x, y)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()

            if text_layer is None:
                text_layer = self._find_new_layer(image, before_ids)
            if text_layer is None:
                # Issue #15: return an explicit error instead of a placeholder
                # success so clients never chain ops on a fake handle.
                return {
                    "status": "error",
                    "error":  "add_text: no text layer was created (no PDB procedure succeeded)",
                }

            return {
                "status": "success",
                "results": {
                    "layer_name":  text_layer.get_name(),
                    "layer_id":    text_layer.get_id(),
                    "text_width":  text_layer.get_width(),
                    "text_height": text_layer.get_height(),
                    "position":    [x, y],
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _edit_text(self, params):
        """Edit an existing text layer."""
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", "")
            new_text    = params.get("text", None)
            new_font    = params.get("font", None)
            new_size    = params.get("size", None)
            new_color   = params.get("color", None)
            image    = self._get_image(image_index)
            layer    = self._resolve_layer(image, layer_name, None)
            pdb      = Gimp.get_pdb()
            image.undo_group_start()
            try:
                if new_text is not None:
                    proc = pdb.lookup_procedure("gimp-text-layer-set-text")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("layer", layer)
                        cfg.set_property("text",  new_text)
                        proc.run(cfg)
                if new_font is not None:
                    proc = pdb.lookup_procedure("gimp-text-layer-set-font")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("layer", layer)
                        cfg.set_property("font",  new_font)
                        proc.run(cfg)
                if new_size is not None:
                    proc = pdb.lookup_procedure("gimp-text-layer-set-font-size")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("layer",     layer)
                        cfg.set_property("font-size", float(new_size))
                        cfg.set_property("unit",      Gimp.Unit.PIXEL)
                        proc.run(cfg)
                if new_color is not None:
                    proc = pdb.lookup_procedure("gimp-text-layer-set-color")
                    if proc:
                        cfg = proc.create_config()
                        cfg.set_property("layer", layer)
                        cfg.set_property("color", Gegl.Color.new(new_color))
                        proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _warp_region(self, params):
        """Warp / liquify a region of pixels to deform facial features.

        Uses plug-in-iwarp (interactive warp) to push pixels in a direction.
        Useful for subtle expressions: turning a neutral mouth into a smile by
        pushing corners upward, etc.

        params:
          image_index  — which image
          layer_name   — optional layer
          vectors      — list of warp vectors: [{x, y, dx, dy, radius, amount}]
                         x/y: pixel coords of warp center
                         dx/dy: push direction in pixels (positive y = down)
                         radius: influence radius in pixels (default 40)
                         amount: deform strength 0-1 (default 0.3)
        """
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            vectors     = params.get("vectors", [])
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            pdb      = Gimp.get_pdb()

            image.undo_group_start()
            try:
                for v in vectors:
                    x      = float(v.get("x", 0))
                    y      = float(v.get("y", 0))
                    dx     = float(v.get("dx", 0))
                    dy     = float(v.get("dy", 0))
                    radius = float(v.get("radius", 40))
                    amount = float(v.get("amount", 0.3))

                    # Try GEGL warp operation first (GIMP 3 native approach)
                    try:
                        Gegl.init(None)
                        buf        = drawable.get_buffer()
                        shadow_buf = drawable.get_shadow_buffer()
                        graph      = Gegl.Node()

                        src = graph.create_child("gegl:buffer-source")
                        src.set_property("buffer", buf)

                        warp = graph.create_child("gegl:warp")
                        warp.set_property("behavior",    0)        # 0 = move
                        warp.set_property("strength",    amount)
                        warp.set_property("size",        radius)
                        warp.set_property("hardness",    0.5)
                        # stamp one warp stroke at (x,y) → (x+dx, y+dy)
                        # GEGL warp builds strokes via the "stroke" property
                        stroke = [(x, y), (x + dx, y + dy)]
                        warp.set_property("stroke", stroke)

                        out = graph.create_child("gegl:write-buffer")
                        out.set_property("buffer", shadow_buf)

                        src.link(warp)
                        warp.link(out)
                        out.process()

                        shadow_buf.flush()
                        drawable.merge_shadow(True)
                        drawable.update(
                            max(0, int(x - radius - abs(dx))),
                            max(0, int(y - radius - abs(dy))),
                            int(radius * 2 + abs(dx) * 2 + 4),
                            int(radius * 2 + abs(dy) * 2 + 4),
                        )
                    except Exception:
                        # Fallback: plug-in-iwarp if GEGL warp fails
                        proc = pdb.lookup_procedure("plug-in-iwarp")
                        if proc:
                            cfg = proc.create_config()
                            try:
                                cfg.set_property("run-mode",      Gimp.RunMode.NONINTERACTIVE)
                                cfg.set_property("image",         image)
                                cfg.set_property("drawable",      drawable)
                                cfg.set_property("cursor-x",      int(x))
                                cfg.set_property("cursor-y",      int(y))
                                cfg.set_property("pressure",      amount)
                                cfg.set_property("move-max-dist", int(radius))
                                cfg.set_property("deform-type",   0)  # 0 = MOVE
                                cfg.set_property("x",             int(x + dx))
                                cfg.set_property("y",             int(y + dy))
                                proc.run(cfg)
                            except Exception:
                                pass
            finally:
                image.undo_group_end()

            Gimp.displays_flush()
            return {"status": "success", "results": {"warped_vectors": len(vectors)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_fonts(self, params):
        """List available fonts."""
        try:
            filt  = params.get("filter", None) or ""
            limit = int(params.get("limit", 100))
            raw = Gimp.fonts_get_list(filt)
            # GIMP 3.2 returns (n, [Gimp.Font, ...]) or just [Gimp.Font, ...]
            if isinstance(raw, tuple):
                font_objs = list(raw[1]) if len(raw) > 1 else []
            else:
                font_objs = list(raw)
            names = []
            for f in font_objs[:limit]:
                if hasattr(f, "get_name"):
                    names.append(f.get_name())
                elif hasattr(f, "name"):
                    names.append(f.name)
                else:
                    names.append(str(f))
            return {"status": "success", "results": {"fonts": names, "count": len(names)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 8 — Filters & Effects
    # =========================================================================

    def _apply_drop_shadow(self, params):
        """Apply drop shadow via manual layer compositing (GIMP 3.2 compatible).

        gegl:drop-shadow and plug-in-drop-shadow are not reliably available in
        GIMP 3.2, so we build the shadow manually:
          1. Duplicate source layer → shadow_layer
          2. Fill it with shadow color (alpha-locked so shape is preserved)
          3. Set opacity and offset
          4. Gaussian-blur with plug-in-gauss
        """
        try:
            from gi.repository import Gegl
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            offset_x    = int(params.get("offset_x", 5))
            offset_y    = int(params.get("offset_y", 5))
            blur_radius = float(params.get("blur_radius", 10))
            color_str   = params.get("color", "black")
            opacity     = float(params.get("opacity", 60))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                pdb = Gimp.get_pdb()

                # 1. Duplicate source layer to use as shadow base
                shadow_layer = drawable.copy()
                src_pos = image.get_item_position(drawable)
                image.insert_layer(shadow_layer, None, src_pos + 1)

                # 2. Fill shadow layer with shadow color, preserving alpha shape
                Gimp.context_set_foreground(Gegl.Color.new(color_str))
                shadow_layer.set_lock_alpha(True)
                Gimp.Drawable.edit_fill(shadow_layer, Gimp.FillType.FOREGROUND)
                shadow_layer.set_lock_alpha(False)

                # 3. Set opacity and offset
                shadow_layer.set_opacity(opacity)
                offs = shadow_layer.get_offsets()
                shadow_layer.set_offsets(offs.offset_x + offset_x, offs.offset_y + offset_y)

                # 4. Blur with plug-in-gauss (always available in GIMP 3.x)
                if blur_radius > 0:
                    size = max(3, int(blur_radius * 2) | 1)  # must be odd, ≥ 3
                    blur_proc = pdb.lookup_procedure("plug-in-gauss")
                    if blur_proc:
                        cfg = blur_proc.create_config()
                        cfg.set_property("image",      image)
                        cfg.set_property("drawable",   shadow_layer)
                        cfg.set_property("horizontal", size)
                        cfg.set_property("vertical",   size)
                        cfg.set_property("method",     0)
                        blur_proc.run(cfg)

                shadow_layer.set_name("Drop Shadow")
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_gaussian_blur(self, params):
        """Apply Gaussian blur."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            radius      = float(params.get("radius", 5.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:gaussian-blur", {
                    "std-dev-x": radius,
                    "std-dev-y": radius,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_pixelate(self, params):
        """Apply pixelate effect."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            block_size  = int(params.get("block_size", 10))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:pixelize", {
                    "size-x": block_size,
                    "size-y": block_size,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_emboss(self, params):
        """Apply emboss effect."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            azimuth     = float(params.get("azimuth", 315))
            elevation   = float(params.get("elevation", 45))
            depth       = float(params.get("depth", 2))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:emboss", {
                    "azimuth":   azimuth,
                    "elevation": elevation,
                    "depth":     depth,
                    "emboss":    True,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_vignette(self, params):
        """Apply vignette effect."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            softness    = float(params.get("softness", 3.0))
            shape       = float(params.get("shape", 1.0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:vignette", {
                    "softness": softness,
                    "shape":    shape,
                    "radius":   1.0,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_noise(self, params):
        """Add noise to a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            amount      = float(params.get("amount", 0.2))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, "gegl:noise-hsv", {
                    "value": amount,
                    "saturation": 0.0,
                    "hue": 0.0,
                })
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_filter(self, params):
        """Apply an arbitrary GEGL operation to a drawable and merge the result.

        Replaces the removed `plug-in-*` PDB procedures: callers name a GEGL op
        (e.g. 'gegl:gaussian-blur') and pass a dict of GEGL properties.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            op_name     = params.get("operation") or params.get("op_name") or ""
            props       = params.get("properties") or params.get("props") or {}
            if not op_name:
                return {"status": "error",
                        "error": "apply_filter: 'operation' is required (e.g. 'gegl:gaussian-blur')"}
            if not isinstance(props, dict):
                return {"status": "error",
                        "error": "apply_filter: 'properties' must be an object mapping prop name to value"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            image.undo_group_start()
            try:
                self._apply_gegl_filter(image, drawable, op_name, props)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {
                "status": "success",
                "results": {
                    "status":        "success",
                    "operation":     op_name,
                    "props_applied": list(props.keys()),
                    "layer_name":    drawable.get_name() if drawable is not None else None,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 9 — Export Pipelines
    # =========================================================================

    def _export_icon_sizes(self, params):
        """Export icon size sets for Android or iOS."""
        try:
            output_dir   = params.get("output_dir", "")
            platform_str = params.get("platform", "android").lower()
            src_index    = int(params.get("source_image_index", 0))
            fmt          = params.get("format", "png")

            ANDROID_SIZES = [
                (48,  "mdpi"), (72, "hdpi"), (96, "xhdpi"),
                (144, "xxhdpi"), (192, "xxxhdpi"), (512, "playstore"),
            ]
            IOS_SIZES = [
                (20, 1), (20, 2), (20, 3),
                (29, 1), (29, 2), (29, 3),
                (40, 2), (40, 3),
                (60, 2), (60, 3),
                (76, 1), (76, 2),
                (84, 2),   # 83.5x2 rounded
                (1024, 1),
            ]

            source_image = self._get_image(src_index)
            os.makedirs(output_dir, exist_ok=True)
            exported = []
            sizes = ANDROID_SIZES if platform_str == "android" else IOS_SIZES

            for entry in sizes:
                if platform_str == "android":
                    px, density = entry
                    out_name = f"icon_{density}_{px}.{fmt}"
                else:
                    px, scale = entry
                    actual_px = int(px * scale)
                    out_name = f"icon_{px}@{scale}x.{fmt}"
                    px = actual_px

                out_path = os.path.join(output_dir, out_name)
                dup = source_image.duplicate()
                try:
                    src_w = dup.get_width()
                    src_h = dup.get_height()
                    aspect = src_w / src_h
                    if aspect >= 1.0:
                        new_w = px
                        new_h = max(1, int(px / aspect))
                    else:
                        new_h = px
                        new_w = max(1, int(px * aspect))
                    dup.scale(new_w, new_h)
                    self._export_to_path(dup, out_path, fmt, 95, True)
                    exported.append({"size": px, "file_path": out_path})
                finally:
                    dup.delete()

            return {"status": "success", "results": {"exported": exported, "count": len(exported), "platform": platform_str}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_web_optimized(self, params):
        """Export as both JPEG and PNG, return comparison."""
        try:
            output_dir    = params.get("output_dir", "")
            jpeg_quality  = int(params.get("jpeg_quality", 85))
            image_index   = int(params.get("image_index", 0))
            max_width     = params.get("max_width", None)
            max_height    = params.get("max_height", None)
            image = self._get_image(image_index)
            os.makedirs(output_dir, exist_ok=True)

            dup = image.duplicate()
            try:
                if max_width or max_height:
                    src_w = dup.get_width()
                    src_h = dup.get_height()
                    mw = int(max_width  or src_w)
                    mh = int(max_height or src_h)
                    aspect = src_w / src_h
                    if src_w / mw > src_h / mh:
                        new_w, new_h = mw, max(1, int(mw / aspect))
                    else:
                        new_h, new_w = mh, max(1, int(mh * aspect))
                    dup.scale(new_w, new_h)

                gio_file = dup.get_file()
                raw_name = gio_file.get_basename().rsplit(".", 1)[0] if gio_file else "image"
                jpeg_path = os.path.join(output_dir, f"{raw_name}.jpg")
                png_path  = os.path.join(output_dir, f"{raw_name}.png")
                jpeg_size = self._export_to_path(dup, jpeg_path, "jpeg", jpeg_quality, True)
                png_size  = self._export_to_path(dup, png_path,  "png",  95,           True)
            finally:
                dup.delete()

            recommendation = "jpeg" if jpeg_size < png_size else "png"
            return {
                "status": "success",
                "results": {
                    "jpeg_path": jpeg_path, "jpeg_size": jpeg_size,
                    "png_path":  png_path,  "png_size":  png_size,
                    "recommendation": recommendation,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _batch_resize(self, params):
        """Resize all open images."""
        try:
            width           = params.get("width", None)
            height          = params.get("height", None)
            scale_factor    = params.get("scale_factor", None)
            maintain_aspect = bool(params.get("maintain_aspect", True))
            images  = Gimp.get_images()
            results = []
            for img in images:
                src_w = img.get_width()
                src_h = img.get_height()
                if scale_factor is not None:
                    new_w = max(1, int(src_w * float(scale_factor)))
                    new_h = max(1, int(src_h * float(scale_factor)))
                else:
                    tw = int(width  or src_w)
                    th = int(height or src_h)
                    if maintain_aspect:
                        if width and not height:
                            new_w = tw
                            new_h = max(1, int(src_h * tw / src_w))
                        elif height and not width:
                            new_h = th
                            new_w = max(1, int(src_w * th / src_h))
                        else:
                            aspect = src_w / src_h
                            if tw / th > aspect:
                                new_h = th
                                new_w = max(1, int(th * aspect))
                            else:
                                new_w = tw
                                new_h = max(1, int(tw / aspect))
                    else:
                        new_w, new_h = tw, th
                img.scale(new_w, new_h)
                results.append({"image_id": img.get_id(), "old_width": src_w, "old_height": src_h, "new_width": new_w, "new_height": new_h})
            Gimp.displays_flush()
            return {"status": "success", "results": {"results": results, "count": len(results)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_sprite_sheet(self, params):
        """Combine frames into a sprite sheet."""
        try:
            from gi.repository import Gegl
            output_path = params.get("output_path", "")
            columns     = params.get("columns", None)
            padding     = int(params.get("padding", 0))
            source      = params.get("source", "layers").lower()
            image_index = int(params.get("image_index", 0))
            import math

            if source == "images":
                frames = Gimp.get_images()
            else:
                src_image = self._get_image(image_index)
                frames = src_image.get_layers()

            if not frames:
                return {"status": "error", "error": "No frames found"}

            # Use first frame dimensions as the cell size
            frame_w = frames[0].get_width()  if hasattr(frames[0], 'get_width')  else frames[0].get_width()
            frame_h = frames[0].get_height() if hasattr(frames[0], 'get_height') else frames[0].get_height()
            n = len(frames)
            cols = int(columns) if columns else max(1, math.ceil(math.sqrt(n)))
            rows = math.ceil(n / cols)

            sheet_w = cols * frame_w + (cols - 1) * padding
            sheet_h = rows * frame_h + (rows - 1) * padding

            sheet = Gimp.Image.new(sheet_w, sheet_h, Gimp.ImageBaseType.RGBA)
            bg_layer = Gimp.Layer.new(sheet, "Background", sheet_w, sheet_h, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
            sheet.insert_layer(bg_layer, None, 0)
            Gimp.context_set_background(Gegl.Color.new("transparent"))
            Gimp.Drawable.edit_fill(bg_layer, Gimp.FillType.TRANSPARENT)

            for i, frame in enumerate(frames):
                col = i % cols
                row = i // cols
                dest_x = col * (frame_w + padding)
                dest_y = row * (frame_h + padding)
                if source == "images":
                    src_layers = frame.get_layers()
                    if not src_layers:
                        continue
                    src_drawable = src_layers[0]
                    frame.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, frame.get_width(), frame.get_height())
                else:
                    src_drawable = frame
                    frame.get_image().select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, frame_w, frame_h)
                Gimp.edit_copy([src_drawable])
                pasted = Gimp.edit_paste(bg_layer, True)[0]
                pasted.set_offsets(dest_x, dest_y)
                Gimp.floating_sel_anchor(pasted)

            self._export_to_path(sheet, output_path, "png", 95, True)
            sheet.delete()
            return {
                "status": "success",
                "results": {
                    "file_path":    output_path,
                    "columns":      cols,
                    "rows":         rows,
                    "frame_width":  frame_w,
                    "frame_height": frame_h,
                    "count":        n,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_social_media_kit(self, params):
        """Export for multiple social media platforms."""
        try:
            output_dir  = params.get("output_dir", "")
            platforms   = params.get("platforms", None)
            image_index = int(params.get("image_index", 0))

            PLATFORM_SIZES = {
                "instagram_square":   (1080, 1080),
                "instagram_story":    (1080, 1920),
                "twitter_header":     (1500, 500),
                "facebook_cover":     (820,  312),
                "youtube_thumbnail":  (1280, 720),
            }

            target_platforms = platforms if platforms else list(PLATFORM_SIZES.keys())
            source_image = self._get_image(image_index)
            os.makedirs(output_dir, exist_ok=True)
            exported = []

            for platform_name in target_platforms:
                if platform_name not in PLATFORM_SIZES:
                    continue
                target_w, target_h = PLATFORM_SIZES[platform_name]
                dup = source_image.duplicate()
                try:
                    src_w = dup.get_width()
                    src_h = dup.get_height()
                    # Scale to cover target (crop to exact size)
                    scale = max(target_w / src_w, target_h / src_h)
                    scaled_w = max(1, int(src_w * scale))
                    scaled_h = max(1, int(src_h * scale))
                    dup.scale(scaled_w, scaled_h)
                    # Crop to exact target
                    crop_x = (scaled_w - target_w) // 2
                    crop_y = (scaled_h - target_h) // 2
                    dup.crop(target_w, target_h, crop_x, crop_y)
                    out_path = os.path.join(output_dir, f"{platform_name}.png")
                    self._export_to_path(dup, out_path, "png", 95, True)
                    exported.append({"platform": platform_name, "file_path": out_path, "width": target_w, "height": target_h})
                finally:
                    dup.delete()

            return {"status": "success", "results": {"exported": exported, "count": len(exported)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 10 — Utility
    # =========================================================================

    def _list_images(self, params):
        """List all open images."""
        try:
            images = Gimp.get_images()
            image_list = []
            base_type_map = {
                Gimp.ImageBaseType.RGB:     "RGB",
                Gimp.ImageBaseType.GRAY:    "Grayscale",
                Gimp.ImageBaseType.INDEXED: "Indexed",
            }
            for i, img in enumerate(images):
                try:
                    gio_file = img.get_file()
                    file_path = gio_file.get_path() if gio_file else "Untitled"
                    image_list.append({
                        "index":      i,
                        "image_id":   img.get_id(),
                        "name":       gio_file.get_basename() if gio_file else f"Untitled_{i}",
                        "width":      img.get_width(),
                        "height":     img.get_height(),
                        "color_mode": base_type_map.get(img.get_base_type(), "Unknown"),
                        "num_layers": len(img.get_layers()),
                        "file_path":  file_path,
                        "is_dirty":   img.is_dirty() if hasattr(img, "is_dirty") else None,
                    })
                except Exception as ex:
                    image_list.append({"index": i, "error": str(ex)})
            return {"status": "success", "results": {"images": image_list, "count": len(image_list)}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_active_image(self, params):
        """Raise a specific image to the front."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            displays = Gimp.get_displays()
            for display in displays:
                try:
                    if display.get_image().get_id() == image.get_id():
                        Gimp.set_default_context()
                        display.present()
                        break
                except Exception:
                    pass
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "image_id": image.get_id()}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _undo(self, params):
        """Undo N steps."""
        try:
            image_index = int(params.get("image_index", 0))
            steps       = int(params.get("steps", 1))
            image = self._get_image(image_index)
            done = 0
            for _ in range(steps):
                if image.undo():
                    done += 1
                else:
                    break
            Gimp.displays_flush()
            return {"status": "success", "results": {"steps_undone": done}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _redo(self, params):
        """Redo N steps."""
        try:
            image_index = int(params.get("image_index", 0))
            steps       = int(params.get("steps", 1))
            image = self._get_image(image_index)
            done = 0
            for _ in range(steps):
                if image.redo():
                    done += 1
                else:
                    break
            Gimp.displays_flush()
            return {"status": "success", "results": {"steps_redone": done}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _convert_color_mode(self, params):
        """Convert image color mode."""
        try:
            image_index = int(params.get("image_index", 0))
            mode        = params.get("mode", "RGB").upper()
            num_colors  = int(params.get("num_colors", 256))
            image = self._get_image(image_index)
            image.undo_group_start()
            try:
                if mode in ("RGB", "RGBA"):
                    image.convert_rgb()
                    if mode == "RGBA":
                        # Add alpha channel to all layers
                        for layer in image.get_layers():
                            if not layer.has_alpha():
                                layer.add_alpha()
                elif mode in ("GRAY", "GRAYA"):
                    image.convert_grayscale()
                    if mode == "GRAYA":
                        for layer in image.get_layers():
                            if not layer.has_alpha():
                                layer.add_alpha()
                elif mode == "INDEXED":
                    image.convert_indexed(
                        Gimp.ConvertDitherType.NO_DITHER,
                        Gimp.ConvertPaletteType.GENERATE,
                        num_colors, False, False, ""
                    )
                else:
                    return {"status": "error", "error": f"Unknown mode: {mode}"}
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "mode": mode}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _close_image(self, params):
        """Close an image, optionally saving first."""
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            save_first  = bool(params.get("save_first", False))
            image = self._get_image(image_index)
            if save_first:
                img_file = image.get_file()
                if img_file:
                    xcf_path = img_file.get_path().rsplit(".", 1)[0] + ".xcf"
                else:
                    import tempfile
                    xcf_path = os.path.join(tempfile.gettempdir(), f"gimp_backup_{image.get_id()}.xcf")
                gio_file = Gio.File.new_for_path(xcf_path)
                pdb = Gimp.get_pdb()
                proc = pdb.lookup_procedure("gimp-xcf-save")
                if proc:
                    cfg = proc.create_config()
                    cfg.set_property("image", image)
                    cfg.set_property("file", gio_file)
                    proc.run(cfg)
            # Delete all displays for this image
            for display in Gimp.get_displays():
                try:
                    if display.get_image().get_id() == image.get_id():
                        Gimp.Display.delete(display)
                except Exception:
                    pass
            image.delete()
            return {"status": "success", "results": {"status": "success"}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_selection_bounds(self, params):
        """Get selection bounding rectangle."""
        try:
            image = self._get_image(int(params.get("image_index", 0)))
            _ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
            return {
                "status": "success",
                "results": {
                    "has_selection": bool(non_empty),
                    "x":      x1,
                    "y":      y1,
                    "width":  x2 - x1,
                    "height": y2 - y1,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_pixel_color(self, params):
        """Get color of a single pixel."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            x           = int(params.get("x", 0))
            y           = int(params.get("y", 0))
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            pixel    = drawable.get_pixel(x, y)
            # GIMP 3.2: get_pixel returns a Gegl.Color object
            if hasattr(pixel, 'get_rgba'):
                rf, gf, bf, af = pixel.get_rgba()
                r, g, b, a = int(rf*255), int(gf*255), int(bf*255), int(af*255)
            else:
                # Fallback: old tuple format (num_channels, bytes_array)
                channels = list(pixel[1]) if hasattr(pixel[1], '__iter__') else []
                r = channels[0] if len(channels) > 0 else 0
                g = channels[1] if len(channels) > 1 else 0
                b = channels[2] if len(channels) > 2 else 0
                a = channels[3] if len(channels) > 3 else 255
            color_hex = f"#{r:02x}{g:02x}{b:02x}"
            return {
                "status": "success",
                "results": {
                    "color_hex": color_hex,
                    "color_rgb": [r, g, b],
                    "alpha":     a,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _batch(self, params):
        """Execute a pipeline of {type, params} tool calls in one round-trip.

        Cuts TCP overhead on long flatting/rendering passes. Each sub-call
        is dispatched through the same code path as a direct request, so
        behavior matches single-call mode exactly.
        """
        try:
            operations    = params.get("operations") or []
            stop_on_error = bool(params.get("stop_on_error", True))
            if not isinstance(operations, list):
                return {"status": "error", "error": "batch: 'operations' must be a list"}
            if "batch" in {op.get("type") for op in operations if isinstance(op, dict)}:
                return {"status": "error",
                        "error": "batch: nested batch operations are not supported"}

            results = []
            for i, op in enumerate(operations):
                if not isinstance(op, dict) or "type" not in op:
                    entry = {"status": "error",
                             "error": f"operation #{i} is missing 'type'",
                             "op_index": i}
                    results.append(entry)
                    if stop_on_error:
                        break
                    continue

                sub_request = json.dumps({
                    "type":   op["type"],
                    "params": op.get("params") or {},
                })
                try:
                    r = self.execute_command(sub_request)
                except Exception as e:
                    r = {"status": "error", "error": str(e),
                         "traceback": traceback.format_exc()}

                entry = dict(r) if isinstance(r, dict) else {"status": "success", "result": r}
                entry["op_index"] = i
                entry["op_type"]  = op["type"]
                results.append(entry)
                if stop_on_error and entry.get("status") != "success":
                    break

            successes = sum(1 for r in results if r.get("status") == "success")
            return {"status": "success", "results": {
                "status":    "success",
                "total":     len(operations),
                "executed":  len(results),
                "successes": successes,
                "failures":  len(results) - successes,
                "results":   results,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_layer_thumbnail(self, params):
        """Return a small PNG thumbnail of a layer as base64.

        Much lighter than get_image_bitmap — uses Gimp.Drawable.get_thumbnail
        to get a pre-scaled GdkPixbuf and encodes it to PNG in one step.
        """
        try:
            import base64
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            max_size    = int(params.get("max_size", 128))

            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)

            w = layer.get_width()
            h = layer.get_height()
            if w <= 0 or h <= 0:
                return {"status": "error", "error": f"layer has zero size ({w}x{h})"}

            scale = min(max_size / w, max_size / h, 1.0)
            thumb_w = max(1, int(w * scale))
            thumb_h = max(1, int(h * scale))

            alpha_enum = getattr(Gimp.PixbufTransparency, "KEEP_ALPHA", None)
            if alpha_enum is None:
                alpha_enum = getattr(Gimp.PixbufTransparency, "SMALL_CHECKS", 0)

            pixbuf = layer.get_thumbnail(thumb_w, thumb_h, alpha_enum)
            if pixbuf is None:
                return {"status": "error", "error": "get_thumbnail returned None"}

            # GdkPixbuf.save_to_bufferv returns (ok, bytes) — signature varies
            # across GI bindings; handle both the tuple and the data-only form.
            save_result = pixbuf.save_to_bufferv("png", [], [])
            if isinstance(save_result, tuple) and len(save_result) >= 2:
                ok_flag, data = save_result[0], save_result[1]
                if not ok_flag:
                    return {"status": "error", "error": "pixbuf save_to_bufferv returned !ok"}
            else:
                data = save_result

            png_bytes = bytes(data) if data is not None else b""
            if not png_bytes:
                return {"status": "error", "error": "pixbuf produced empty PNG"}

            return {"status": "success", "results": {
                "status":       "success",
                "layer_name":   layer.get_name(),
                "width":        thumb_w,
                "height":       thumb_h,
                "mime_type":    "image/png",
                "size_bytes":   len(png_bytes),
                "data_base64":  base64.b64encode(png_bytes).decode("ascii"),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _begin_transaction(self, params):
        """Open a named undo group on an image. Pair with commit or rollback."""
        try:
            name        = (params.get("name") or "").strip()
            image_index = int(params.get("image_index", 0))
            if not name:
                return {"status": "error", "error": "begin_transaction: 'name' is required"}
            if name in self._active_transactions:
                return {"status": "error",
                        "error": f"transaction '{name}' is already active — commit or rollback first"}
            image = self._get_image(image_index)
            image.undo_group_start()
            self._active_transactions[name] = image_index
            return {"status": "success", "results": {
                "status":      "success",
                "name":        name,
                "image_index": image_index,
                "active":      sorted(self._active_transactions.keys()),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _commit_transaction(self, params):
        """Close a named undo group on its recorded image."""
        try:
            name = (params.get("name") or "").strip()
            if not name:
                return {"status": "error", "error": "commit_transaction: 'name' is required"}
            image_index = self._active_transactions.pop(name, None)
            if image_index is None:
                return {"status": "error", "error": f"no active transaction named '{name}'"}
            image = self._get_image(image_index)
            image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":      "success",
                "name":        name,
                "image_index": image_index,
                "active":      sorted(self._active_transactions.keys()),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _rollback_transaction(self, params):
        """Close and undo a named undo group (everything inside rolls back)."""
        try:
            name = (params.get("name") or "").strip()
            if not name:
                return {"status": "error", "error": "rollback_transaction: 'name' is required"}
            image_index = self._active_transactions.pop(name, None)
            if image_index is None:
                return {"status": "error", "error": f"no active transaction named '{name}'"}
            image = self._get_image(image_index)
            image.undo_group_end()
            try:
                image.undo()
            except Exception:
                pass
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":      "success",
                "name":        name,
                "image_index": image_index,
                "rolled_back": True,
                "active":      sorted(self._active_transactions.keys()),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_canvas_info(self, params):
        """Return a consolidated snapshot of the active image's state.

        One call replaces the get_image_metadata + list_layers + selection
        bounds round-trip chain most agents do at the start of every task.
        """
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)

            width  = image.get_width()
            height = image.get_height()

            resolution = None
            try:
                res = image.get_resolution()
                if isinstance(res, tuple) and len(res) >= 3:
                    resolution = {"x": float(res[1]), "y": float(res[2])}
                elif isinstance(res, tuple) and len(res) == 2:
                    resolution = {"x": float(res[0]), "y": float(res[1])}
            except Exception:
                pass

            MODE_MAP = {
                Gimp.ImageBaseType.RGB:     "RGB",
                Gimp.ImageBaseType.GRAY:    "Grayscale",
                Gimp.ImageBaseType.INDEXED: "Indexed",
            }
            try: color_mode = MODE_MAP.get(image.get_base_type(), str(image.get_base_type()))
            except Exception: color_mode = None

            layers        = image.get_layers() or []
            active_layers = image.get_selected_layers() or []
            active_layer  = active_layers[0] if active_layers else (layers[0] if layers else None)

            selection_bounds = None
            try:
                bounds = Gimp.Selection.bounds(image)
                # Gimp.Selection.bounds returns (ok, non_empty, x1, y1, x2, y2)
                if isinstance(bounds, tuple) and len(bounds) >= 6 and bounds[1]:
                    selection_bounds = {
                        "x":      int(bounds[2]),
                        "y":      int(bounds[3]),
                        "width":  int(bounds[4] - bounds[2]),
                        "height": int(bounds[5] - bounds[3]),
                    }
            except Exception:
                pass

            has_alpha = None
            if active_layer is not None:
                try: has_alpha = bool(active_layer.has_alpha())
                except Exception: pass

            try: is_dirty = bool(image.is_dirty())
            except Exception: is_dirty = None

            return {"status": "success", "results": {
                "status":               "success",
                "image_id":             image.get_id(),
                "width":                width,
                "height":               height,
                "resolution":           resolution,
                "color_mode":           color_mode,
                "num_layers":           len(layers),
                "active_layer":         active_layer.get_name() if active_layer is not None else None,
                "active_layer_id":      active_layer.get_id()   if active_layer is not None else None,
                "active_layer_visible": bool(active_layer.get_visible()) if active_layer is not None else None,
                "selection_bounds":     selection_bounds,
                "has_alpha":            has_alpha,
                "is_dirty":             is_dirty,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _get_histogram(self, params):
        """Get histogram statistics for a layer channel."""
        try:
            CHANNEL_MAP = {
                "value": Gimp.HistogramChannel.VALUE,
                "red":   Gimp.HistogramChannel.RED,
                "green": Gimp.HistogramChannel.GREEN,
                "blue":  Gimp.HistogramChannel.BLUE,
                "alpha": Gimp.HistogramChannel.ALPHA,
            }
            image_index = int(params.get("image_index", 0))
            channel_str = params.get("channel", "value")
            image    = self._get_image(image_index)
            drawable = (image.get_selected_layers() or image.get_layers() or [None])[0]
            channel  = CHANNEL_MAP.get(channel_str.lower(), Gimp.HistogramChannel.VALUE)
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-drawable-histogram")
            if proc:
                cfg = proc.create_config()
                cfg.set_property("drawable",    drawable)
                cfg.set_property("channel",     channel)
                cfg.set_property("start-range", 0.0)
                cfg.set_property("end-range",   1.0)
                result = proc.run(cfg)
                # Return values: mean, std-dev, median, pixels, count, percentile
                def _safe(idx):
                    try:
                        return result.index(idx)
                    except Exception:
                        return 0
                return {
                    "status": "success",
                    "results": {
                        "mean":    _safe(0),
                        "std_dev": _safe(1),
                        "median":  _safe(2),
                        "pixels":  _safe(3),
                        "count":   _safe(4),
                    }
                }
            else:
                return {"status": "error", "error": "gimp-drawable-histogram not available"}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 11 — Discovery (3.2 migration helpers)
    # =========================================================================

    def _pspec_info(self, spec):
        """Serialize a GObject.ParamSpec into a JSON-safe dict (name/type/blurb)."""
        try:
            return {
                "name":  getattr(spec, "name", str(spec)),
                "type":  getattr(getattr(spec, "value_type", None), "name", "unknown"),
                "blurb": getattr(spec, "blurb", "") or "",
            }
        except Exception:
            return {"name": str(spec), "type": "unknown", "blurb": ""}

    def _get_pdb_procedure_info(self, params):
        """Return metadata for a PDB procedure: blurb, help, authors, args, return values.

        Lets callers discover the real signature before invoking a procedure,
        which is the 3.2 replacement for poking at `Gimp.get_pdb().run_procedure`.
        """
        try:
            name = (params.get("name") or "").strip()
            if not name:
                return {"status": "error", "error": "get_pdb_procedure_info: 'name' is required"}
            pdb = Gimp.get_pdb()
            proc = pdb.lookup_procedure(name)
            if proc is None:
                return {"status": "error", "error": f"PDB procedure not found: {name}"}

            def _attr(getter, default=""):
                try:
                    val = getter()
                    return val if val is not None else default
                except Exception:
                    return default

            args    = [self._pspec_info(s) for s in (_attr(proc.get_arguments,    []) or [])]
            returns = [self._pspec_info(s) for s in (_attr(proc.get_return_values, []) or [])]

            return {
                "status": "success",
                "results": {
                    "name":          name,
                    "blurb":         _attr(proc.get_blurb),
                    "help":          _attr(proc.get_help),
                    "authors":       _attr(proc.get_authors),
                    "copyright":     _attr(proc.get_copyright),
                    "date":          _attr(proc.get_date),
                    "arguments":     args,
                    "return_values": returns,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_blend_modes(self, params):
        """Return the set of blend-mode strings accepted by set_layer_properties / paint_stroke.

        Each entry records the user-facing key, the underlying Gimp.LayerMode
        enum name, and whether the enum exists in this GIMP build.
        """
        try:
            modes = []
            for key, enum_name in sorted(self._BLEND_MODE_ENUM_MAP.items()):
                available = hasattr(Gimp.LayerMode, enum_name)
                modes.append({
                    "key":       key,
                    "enum_name": enum_name,
                    "available": available,
                })
            available_count = sum(1 for m in modes if m["available"])
            return {
                "status": "success",
                "results": {
                    "count":           len(modes),
                    "available_count": available_count,
                    "modes":           modes,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_gegl_operations(self, params):
        """List available GEGL operations matching an optional prefix (e.g. 'gegl:blur').

        Use together with apply_filter to discover ops for DrawableFilter without
        guessing op names the old `plug-in-*` PDB procedures used to own.
        """
        try:
            from gi.repository import Gegl
            prefix = params.get("prefix") or ""
            contains = params.get("contains") or ""

            # Gegl's op registry is empty until Gegl.init runs in the plugin's
            # Python context. The call is idempotent, so initializing here is safe.
            try:
                Gegl.init(None)
            except Exception:
                pass

            ops = []
            try:
                raw = Gegl.list_operations()
                if isinstance(raw, (list, tuple)):
                    ops = [str(o) for o in raw]
                elif raw is not None:
                    ops = [str(o) for o in list(raw)]
            except Exception as gegl_err:
                return {"status": "error",
                        "error": f"Gegl.list_operations failed: {gegl_err}",
                        "traceback": traceback.format_exc()}

            if prefix:
                ops = [o for o in ops if o.startswith(prefix)]
            if contains:
                needle = contains.lower()
                ops = [o for o in ops if needle in o.lower()]
            ops.sort()

            return {
                "status": "success",
                "results": {
                    "count":      len(ops),
                    "operations": ops,
                    "prefix":     prefix,
                    "contains":   contains,
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 12 — Paths
    # =========================================================================

    def _resolve_path(self, image, path_name):
        """Look up a path by name in an image. Returns None if not found."""
        if not path_name:
            return None
        for p in (image.get_paths() or []):
            if p.get_name() == path_name:
                return p
        return None

    def _list_paths(self, params):
        """Enumerate an image's paths with {id, name, visible}."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            paths = []
            for p in (image.get_paths() or []):
                try:    visible = bool(p.get_visible())
                except Exception: visible = None
                paths.append({
                    "id":      p.get_id(),
                    "name":    p.get_name(),
                    "visible": visible,
                })
            return {"status": "success", "results": {
                "status": "success",
                "count":  len(paths),
                "paths":  paths,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _rename_path(self, params):
        """Rename a path via path.set_name."""
        try:
            image_index = int(params.get("image_index", 0))
            path_name   = params.get("path_name") or ""
            new_name    = (params.get("new_name") or "").strip()
            if not path_name or not new_name:
                return {"status": "error",
                        "error": "rename_path: 'path_name' and 'new_name' are required"}
            image = self._get_image(image_index)
            path  = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}
            path.set_name(new_name)
            return {"status": "success", "results": {
                "status": "success", "old_name": path_name, "new_name": path.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _delete_path(self, params):
        """Remove a path via image.remove_path."""
        try:
            image_index = int(params.get("image_index", 0))
            path_name   = params.get("path_name") or ""
            if not path_name:
                return {"status": "error", "error": "delete_path: 'path_name' is required"}
            image = self._get_image(image_index)
            path  = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}
            image.remove_path(path)
            Gimp.displays_flush()
            return {"status": "success", "results": {"status": "success", "path_name": path_name}}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_path_visible(self, params):
        """Toggle a path's visibility via path.set_visible."""
        try:
            image_index = int(params.get("image_index", 0))
            path_name   = params.get("path_name") or ""
            visible     = bool(params.get("visible", True))
            if not path_name:
                return {"status": "error", "error": "set_path_visible: 'path_name' is required"}
            image = self._get_image(image_index)
            path  = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}
            path.set_visible(visible)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status": "success", "path_name": path_name, "visible": visible,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _selection_to_path(self, params):
        """Convert the current selection to a path via plug-in-sel2path.

        Uses GIMP's built-in selection-to-path plug-in with its default
        tuning. Callers that need finer control can drive the procedure
        directly via apply_filter / call_api.
        """
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            layers = image.get_layers() or []
            drawable = (image.get_selected_layers() or layers or [None])[0]
            if drawable is None:
                return {"status": "error", "error": "selection_to_path: image has no layers"}

            paths_before = {p.get_id() for p in (image.get_paths() or [])}
            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure("plug-in-sel2path")
            if proc is None:
                return {"status": "error", "error": "plug-in-sel2path not available"}
            image.undo_group_start()
            try:
                cfg = proc.create_config()
                cfg.set_property("run-mode",  Gimp.RunMode.NONINTERACTIVE)
                cfg.set_property("image",     image)
                cfg.set_property("drawables", [drawable])
                proc.run(cfg)
            finally:
                image.undo_group_end()
            new_paths = [p for p in (image.get_paths() or []) if p.get_id() not in paths_before]
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "new_paths": [{"id": p.get_id(), "name": p.get_name()} for p in new_paths],
                "count":     len(new_paths),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _export_path_as_svg(self, params):
        """Export a named path to an SVG file via gimp-image-export-path-to-file."""
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            path_name   = params.get("path_name") or ""
            file_path   = params.get("file_path") or ""
            if not path_name:
                return {"status": "error", "error": "export_path_as_svg: 'path_name' is required"}
            if not file_path:
                return {"status": "error", "error": "export_path_as_svg: 'file_path' is required"}
            image = self._get_image(image_index)
            path  = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}
            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-image-export-path-to-file")
            if proc is None:
                return {"status": "error",
                        "error": "gimp-image-export-path-to-file not available"}
            cfg = proc.create_config()
            cfg.set_property("image", image)
            cfg.set_property("file",  Gio.File.new_for_path(file_path))
            cfg.set_property("path",  path)
            proc.run(cfg)
            size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else None
            return {"status": "success", "results": {
                "status":     "success",
                "path_name":  path_name,
                "file_path":  file_path,
                "size_bytes": size_bytes,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _add_text_on_path(self, params):
        """Render text along a path.

        Text-on-path is a UI-only feature in GIMP 3.2's PDB — there is no
        single procedure that renders text warped to a curve. This tool
        returns a clear 'not available' error with a pointer to the
        UI workflow or the two-step alternative (text_layer_to_path +
        path_stroke) so callers get structured feedback instead of a
        silent fallback.
        """
        return {"status": "error",
                "error": "add_text_on_path: GIMP 3.2 does not expose a text-on-path PDB "
                         "procedure (Layer → Text along path is UI-only). Workaround: "
                         "use add_text to lay the text, then text_layer_to_path + "
                         "path_stroke for a curve-aligned outline."}

    # =========================================================================
    # CATEGORY 14 — Non-Destructive Filters
    # =========================================================================

    def _resolve_filter(self, drawable, filter_id):
        """Look up a DrawableFilter on a drawable by id. Returns None if not found."""
        if filter_id is None:
            return None
        try:
            filter_id = int(filter_id)
        except (TypeError, ValueError):
            return None
        for f in (drawable.get_filters() or []):
            try:
                if f.get_id() == filter_id:
                    return f
            except Exception:
                continue
        return None

    def _merge_layer_filter(self, params):
        """Promote a single live filter to destructive via drawable.merge_filter."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            filter_id   = params.get("filter_id")
            if filter_id is None:
                return {"status": "error", "error": "merge_layer_filter: 'filter_id' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            filter_obj = self._resolve_filter(drawable, filter_id)
            if filter_obj is None:
                return {"status": "error", "error": f"filter_id {filter_id} not found on layer"}
            image.undo_group_start()
            try:
                drawable.merge_filter(filter_obj)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "filter_id": filter_id,
                "layer_name": drawable.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _reorder_layer_filter(self, params):
        """Change a filter's position in the NDE stack.

        GIMP 3.2 does not expose a reorder API (no Drawable.reorder_filter
        on the Python binding, no gimp-drawable-reorder-filter PDB proc).
        The API shape is kept stable so scripts can call this tool across
        future builds; for now it returns a structured 'not available'
        error with a remove + reapply workaround suggestion.
        """
        _ = params  # params retained for future live implementation
        return {"status": "error",
                "error": "reorder_layer_filter: no reorder API is exposed in GIMP 3.2 "
                         "(Drawable.reorder_filter missing, gimp-drawable-reorder-filter "
                         "absent). Workaround: remove_layer_filter then "
                         "apply_filter_nondestructive in the desired order."}

    def _toggle_layer_filter(self, params):
        """Show / hide a live filter via filter.set_visible."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            filter_id   = params.get("filter_id")
            visible     = params.get("visible")
            if filter_id is None:
                return {"status": "error", "error": "toggle_layer_filter: 'filter_id' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            filter_obj = self._resolve_filter(drawable, filter_id)
            if filter_obj is None:
                return {"status": "error", "error": f"filter_id {filter_id} not found on layer"}
            try: current = bool(filter_obj.get_visible())
            except Exception: current = None
            new_state = (not current) if visible is None and current is not None else bool(visible)
            filter_obj.set_visible(new_state)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "filter_id": filter_id,
                "previous":  current,
                "visible":   new_state,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _remove_layer_filter(self, params):
        """Remove a live filter from a layer via gimp-drawable-filter-delete.

        Drawable.remove_filter is not exposed in the Python binding in
        current 3.2 builds, so this uses the PDB procedure directly.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            filter_id   = params.get("filter_id")
            if filter_id is None:
                return {"status": "error", "error": "remove_layer_filter: 'filter_id' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            filter_obj = self._resolve_filter(drawable, filter_id)
            if filter_obj is None:
                return {"status": "error", "error": f"filter_id {filter_id} not found on layer"}
            pdb  = Gimp.get_pdb()
            proc = pdb.lookup_procedure("gimp-drawable-filter-delete")
            if proc is None:
                return {"status": "error", "error": "gimp-drawable-filter-delete not available"}
            image.undo_group_start()
            try:
                cfg = proc.create_config()
                cfg.set_property("filter", filter_obj)
                proc.run(cfg)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "filter_id": filter_id,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _update_layer_filter(self, params):
        """Set one or more GEGL properties on a live filter via filter.get_config."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            filter_id   = params.get("filter_id")
            props       = params.get("properties") or {}
            if filter_id is None:
                return {"status": "error", "error": "update_layer_filter: 'filter_id' is required"}
            if not isinstance(props, dict):
                return {"status": "error", "error": "update_layer_filter: 'properties' must be a dict"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            filter_obj = self._resolve_filter(drawable, filter_id)
            if filter_obj is None:
                return {"status": "error", "error": f"filter_id {filter_id} not found on layer"}
            config = filter_obj.get_config()
            if config is None:
                return {"status": "error", "error": "filter has no config object"}
            applied = []
            for k, v in props.items():
                try:
                    config.set_property(k, v)
                    applied.append(k)
                except Exception:
                    pass
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "filter_id": filter_obj.get_id(),
                "applied":   applied,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_layer_filters(self, params):
        """Enumerate non-destructive filters attached to a layer."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            filters = []
            for f in (drawable.get_filters() or []):
                try:    op = f.get_operation_name()
                except Exception: op = None
                try:    name = f.get_name()
                except Exception: name = None
                try:    visible = bool(f.get_visible())
                except Exception: visible = None
                try:    opacity = float(f.get_opacity())
                except Exception: opacity = None
                filters.append({
                    "id":        f.get_id(),
                    "name":      name,
                    "operation": op,
                    "visible":   visible,
                    "opacity":   opacity,
                })
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": drawable.get_name(),
                "count":      len(filters),
                "filters":    filters,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _apply_filter_nondestructive(self, params):
        """Apply a GEGL op to a drawable without merging — keep it as a live filter.

        Mirrors apply_filter's parameter shape but calls append_filter instead
        of merge_filter, so the filter stays editable via update_layer_filter
        / toggle_layer_filter and can later be promoted via merge_layer_filter.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            op_name     = params.get("operation") or params.get("op_name") or ""
            props       = params.get("properties") or params.get("props") or {}
            name        = params.get("name") or op_name

            if not op_name:
                return {"status": "error",
                        "error": "apply_filter_nondestructive: 'operation' is required"}
            if not isinstance(props, dict):
                return {"status": "error",
                        "error": "apply_filter_nondestructive: 'properties' must be a dict"}

            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)

            image.undo_group_start()
            try:
                filter_obj = Gimp.DrawableFilter.new(drawable, op_name, name)
                if filter_obj is None:
                    return {"status": "error",
                            "error": f"DrawableFilter.new returned None for '{op_name}'"}
                config = filter_obj.get_config()
                if config is not None:
                    for k, v in props.items():
                        try: config.set_property(k, v)
                        except Exception: pass
                drawable.append_filter(filter_obj)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":        "success",
                "filter_id":     filter_obj.get_id(),
                "filter_name":   filter_obj.get_name(),
                "operation":     op_name,
                "layer_name":    drawable.get_name(),
                "props_applied": list(props.keys()),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _text_layer_to_path(self, params):
        """Convert a text layer's glyphs to a path via Gimp.Path.new_from_text_layer."""
        try:
            image_index  = int(params.get("image_index", 0))
            text_layer_name = params.get("text_layer_name") or ""
            new_path_name   = (params.get("new_path_name") or "").strip()
            if not text_layer_name:
                return {"status": "error",
                        "error": "text_layer_to_path: 'text_layer_name' is required"}
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, text_layer_name, None)
            if not isinstance(layer, Gimp.TextLayer):
                return {"status": "error",
                        "error": f"layer '{layer.get_name()}' is not a text layer"}
            path = Gimp.Path.new_from_text_layer(image, layer)
            if path is None:
                return {"status": "error", "error": "Gimp.Path.new_from_text_layer returned None"}
            if new_path_name:
                try: path.set_name(new_path_name)
                except Exception: pass
            image.insert_path(path, None, -1)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": text_layer_name,
                "path_id":    path.get_id(),
                "path_name":  path.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _import_svg_as_path(self, params):
        """Import an SVG file as one or more paths via gimp-image-import-paths-from-file.

        The 3.2 proc replaces the 3.0-era gimp-vectors-import-from-file.
        """
        try:
            from gi.repository import Gio
            image_index = int(params.get("image_index", 0))
            file_path   = params.get("file_path", "")
            merge       = bool(params.get("merge", True))
            scale       = bool(params.get("scale", True))

            if not file_path:
                return {"status": "error", "error": "import_svg_as_path: 'file_path' is required"}
            if not os.path.exists(file_path):
                return {"status": "error", "error": f"file not found: {file_path}"}

            image = self._get_image(image_index)
            pdb   = Gimp.get_pdb()
            proc  = pdb.lookup_procedure("gimp-image-import-paths-from-file")
            if proc is None:
                return {"status": "error",
                        "error": "gimp-image-import-paths-from-file not available"}

            paths_before = {p.get_id() for p in (image.get_paths() or [])}
            image.undo_group_start()
            try:
                cfg = proc.create_config()
                cfg.set_property("image", image)
                cfg.set_property("file",  Gio.File.new_for_path(file_path))
                cfg.set_property("merge", merge)
                cfg.set_property("scale", scale)
                proc.run(cfg)
            finally:
                image.undo_group_end()

            imported = [p for p in (image.get_paths() or []) if p.get_id() not in paths_before]
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":      "success",
                "file_path":   file_path,
                "merge":       merge,
                "scale":       scale,
                "imported":    [{"id": p.get_id(), "name": p.get_name()} for p in imported],
                "count":       len(imported),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _path_stroke(self, params):
        """Stroke a named path on a drawable via edit_stroke_item.

        Context (brush, size, opacity, color) is pushed before the stroke
        and popped in finally. Dynamics/hardness/mode are left to the
        existing context — use paint_stroke for a fully parameterised call.
        """
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            path_name   = params.get("path_name") or ""
            brush       = params.get("brush")
            size        = params.get("size")
            opacity     = params.get("opacity")
            color       = params.get("color")

            if not path_name:
                return {"status": "error", "error": "path_stroke: 'path_name' is required"}
            image    = self._get_image(image_index)
            drawable = self._resolve_layer(image, layer_name, None)
            path     = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}

            image.undo_group_start()
            Gimp.context_push()
            try:
                self._apply_paint_context(brush, size, None, opacity, None, color, None, None)
                drawable.edit_stroke_item(path)
            finally:
                Gimp.context_pop()
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": drawable.get_name(),
                "path_name":  path_name,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _path_to_selection(self, params):
        """Convert a named path to a selection using image.select_item."""
        try:
            image_index = int(params.get("image_index", 0))
            path_name   = params.get("path_name") or ""
            operation   = (params.get("operation") or "replace").lower()
            if not path_name:
                return {"status": "error", "error": "path_to_selection: 'path_name' is required"}
            image = self._get_image(image_index)
            path  = self._resolve_path(image, path_name)
            if path is None:
                return {"status": "error", "error": f"path not found: {path_name}"}
            op = self._channel_ops_from_string(operation)
            image.select_item(op, path)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":    "success",
                "path_name": path_name,
                "operation": operation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _path_create(self, params):
        """Create a bezier path and insert it into the image.

        Each entry in `points` is {"anchor":[x,y], "h1":[cx,cy], "h2":[cx,cy]}.
        The first point's anchor starts the stroke; subsequent points are
        reached via cubic-to using the previous point's h2 and the current
        point's h1. h1/h2 default to the anchor (degenerate cubic = straight
        line) when omitted.
        """
        try:
            image_index = int(params.get("image_index", 0))
            name        = params.get("name") or "Path"
            points      = params.get("points") or []
            close       = bool(params.get("close", True))

            if not isinstance(points, list) or not points:
                return {"status": "error",
                        "error": "path_create: 'points' must be a non-empty list"}

            def _xy(val, fallback):
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    return float(val[0]), float(val[1])
                return fallback

            image = self._get_image(image_index)
            path  = Gimp.Path.new(image, name)
            image.insert_path(path, None, -1)

            first = points[0]
            if not isinstance(first, dict):
                return {"status": "error",
                        "error": "path_create: each point must be an object with 'anchor'"}
            anchor0 = _xy(first.get("anchor"), None)
            if anchor0 is None:
                return {"status": "error",
                        "error": "path_create: first point missing 'anchor': [x,y]"}

            stroke_id = path.bezier_stroke_new_moveto(anchor0[0], anchor0[1])

            prev = first
            for cur in points[1:]:
                if not isinstance(cur, dict):
                    continue
                cur_anchor = _xy(cur.get("anchor"), None)
                if cur_anchor is None:
                    continue
                prev_anchor = _xy(prev.get("anchor"), None) or cur_anchor
                prev_h2 = _xy(prev.get("h2"), prev_anchor)
                cur_h1  = _xy(cur.get("h1"),  cur_anchor)
                path.bezier_stroke_cubicto(
                    stroke_id,
                    prev_h2[0], prev_h2[1],
                    cur_h1[0],  cur_h1[1],
                    cur_anchor[0], cur_anchor[1],
                )
                prev = cur

            if close:
                try:
                    path.stroke_close(stroke_id)
                except Exception:
                    pass

            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "path_name":  path.get_name(),
                "path_id":    path.get_id(),
                "num_points": len(points),
                "closed":     close,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # =========================================================================
    # CATEGORY 13 — Channels & Masks
    # =========================================================================

    def _resolve_channel(self, image, channel_name):
        """Look up a channel by name in an image. Returns None if not found."""
        if not channel_name:
            return None
        for ch in (image.get_channels() or []):
            if ch.get_name() == channel_name:
                return ch
        return None

    def _color_to_hex(self, color_obj):
        """Serialize a GeglColor to '#rrggbb' for JSON responses, or None."""
        if color_obj is None:
            return None
        try:
            rgba = color_obj.get_rgba()
            if isinstance(rgba, tuple) and len(rgba) >= 3:
                r, g, b = rgba[0], rgba[1], rgba[2]
                return "#{:02x}{:02x}{:02x}".format(
                    max(0, min(255, int(r * 255))),
                    max(0, min(255, int(g * 255))),
                    max(0, min(255, int(b * 255))),
                )
        except Exception:
            pass
        return None

    def _invert_layer_mask(self, params):
        """Invert a layer's mask in place via drawable.invert."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            mask  = layer.get_mask()
            if mask is None:
                return {"status": "error", "error": f"layer '{layer.get_name()}' has no mask"}
            image.undo_group_start()
            try:
                mask.invert()
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": layer.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _layer_mask_to_selection(self, params):
        """Load a layer's mask into the selection via image.select_item."""
        try:
            image_index = int(params.get("image_index", 0))
            layer_name  = params.get("layer_name", None)
            operation   = (params.get("operation") or "replace").lower()
            image = self._get_image(image_index)
            layer = self._resolve_layer(image, layer_name, None)
            mask  = layer.get_mask()
            if mask is None:
                return {"status": "error", "error": f"layer '{layer.get_name()}' has no mask"}
            op = self._channel_ops_from_string(operation)
            image.select_item(op, mask)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":     "success",
                "layer_name": layer.get_name(),
                "operation":  operation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _quick_mask_toggle(self, params):
        """Enter / exit quick-mask paint mode.

        Quick-mask state isn't exposed via the 3.2 PDB or the Python
        binding in most builds. This implementation probes every known
        access path and returns a clear error if none are available, so
        callers can fall back to UI control without silent misbehavior.
        """
        try:
            image_index = int(params.get("image_index", 0))
            requested   = params.get("state")  # True / False / None(=toggle)
            image = self._get_image(image_index)

            # Probe access paths in order of preference.
            # 1. Python method form (future-proofing)
            if hasattr(image, "get_quick_mask_state") and hasattr(image, "set_quick_mask_state"):
                current = bool(image.get_quick_mask_state())
                new_state = (not current) if requested is None else bool(requested)
                image.set_quick_mask_state(new_state)
                Gimp.displays_flush()
                return {"status": "success", "results": {
                    "status":     "success",
                    "previous":   current,
                    "new_state":  new_state,
                }}

            # 2. PDB procedure form
            pdb = Gimp.get_pdb()
            get_proc = pdb.lookup_procedure("gimp-image-get-quick-mask-state")
            set_proc = pdb.lookup_procedure("gimp-image-set-quick-mask-state")
            if get_proc is not None and set_proc is not None:
                gcfg = get_proc.create_config()
                gcfg.set_property("image", image)
                gresult = get_proc.run(gcfg)
                current = bool(gresult.index(1)) if gresult is not None else False
                new_state = (not current) if requested is None else bool(requested)
                scfg = set_proc.create_config()
                scfg.set_property("image", image)
                scfg.set_property("mask-active", new_state)
                set_proc.run(scfg)
                Gimp.displays_flush()
                return {"status": "success", "results": {
                    "status":    "success",
                    "previous":  current,
                    "new_state": new_state,
                }}

            return {"status": "error",
                    "error": "quick_mask_toggle: neither Gimp.Image.get_quick_mask_state "
                             "nor gimp-image-get-quick-mask-state is available in this "
                             "GIMP build — use the UI (Shift+Q) to toggle quick mask"}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _set_channel_properties(self, params):
        """Set opacity / color / visibility on a named channel."""
        try:
            from gi.repository import Gegl
            image_index  = int(params.get("image_index", 0))
            channel_name = params.get("channel_name") or ""
            opacity      = params.get("opacity")
            color        = params.get("color")
            visible      = params.get("visible")
            if not channel_name:
                return {"status": "error", "error": "set_channel_properties: 'channel_name' is required"}
            image = self._get_image(image_index)
            channel = self._resolve_channel(image, channel_name)
            if channel is None:
                return {"status": "error", "error": f"channel not found: {channel_name}"}

            applied = {}
            if opacity is not None:
                try:
                    channel.set_opacity(float(opacity))
                    applied["opacity"] = float(opacity)
                except Exception:
                    pass
            if color is not None:
                try:
                    channel.set_color(Gegl.Color.new(color))
                    applied["color"] = color
                except Exception:
                    pass
            if visible is not None:
                try:
                    channel.set_visible(bool(visible))
                    applied["visible"] = bool(visible)
                except Exception:
                    pass
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "channel_name": channel_name,
                "applied":      applied,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _rename_channel(self, params):
        """Rename a named channel via channel.set_name."""
        try:
            image_index  = int(params.get("image_index", 0))
            channel_name = params.get("channel_name") or ""
            new_name     = (params.get("new_name") or "").strip()
            if not channel_name:
                return {"status": "error", "error": "rename_channel: 'channel_name' is required"}
            if not new_name:
                return {"status": "error", "error": "rename_channel: 'new_name' is required"}
            image = self._get_image(image_index)
            channel = self._resolve_channel(image, channel_name)
            if channel is None:
                return {"status": "error", "error": f"channel not found: {channel_name}"}
            channel.set_name(new_name)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":   "success",
                "old_name": channel_name,
                "new_name": channel.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _delete_channel(self, params):
        """Remove a named channel via image.remove_channel."""
        try:
            image_index  = int(params.get("image_index", 0))
            channel_name = params.get("channel_name") or ""
            if not channel_name:
                return {"status": "error", "error": "delete_channel: 'channel_name' is required"}
            image = self._get_image(image_index)
            channel = self._resolve_channel(image, channel_name)
            if channel is None:
                return {"status": "error", "error": f"channel not found: {channel_name}"}
            image.remove_channel(channel)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "channel_name": channel_name,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _duplicate_channel(self, params):
        """Duplicate a channel via channel.copy + image.insert_channel."""
        try:
            image_index  = int(params.get("image_index", 0))
            channel_name = params.get("channel_name") or ""
            new_name     = (params.get("new_name") or "").strip()
            if not channel_name:
                return {"status": "error", "error": "duplicate_channel: 'channel_name' is required"}

            image = self._get_image(image_index)
            src = self._resolve_channel(image, channel_name)
            if src is None:
                return {"status": "error", "error": f"channel not found: {channel_name}"}

            dup = src.copy()
            if dup is None:
                return {"status": "error", "error": "channel.copy returned None"}
            if new_name:
                try: dup.set_name(new_name)
                except Exception: pass
            image.insert_channel(dup, None, -1)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":        "success",
                "source_name":   channel_name,
                "new_id":        dup.get_id(),
                "new_name":      dup.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _channel_to_selection(self, params):
        """Load a named channel back into the selection via image.select_item."""
        try:
            image_index = int(params.get("image_index", 0))
            channel_name = params.get("channel_name") or ""
            operation    = (params.get("operation") or "replace").lower()
            if not channel_name:
                return {"status": "error", "error": "channel_to_selection: 'channel_name' is required"}
            image = self._get_image(image_index)
            channel = self._resolve_channel(image, channel_name)
            if channel is None:
                return {"status": "error", "error": f"channel not found: {channel_name}"}
            op = self._channel_ops_from_string(operation)
            image.select_item(op, channel)
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":       "success",
                "channel_name": channel_name,
                "operation":    operation,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _save_selection_as_channel(self, params):
        """Save the current selection as a named channel via Gimp.Selection.save."""
        try:
            image_index = int(params.get("image_index", 0))
            name        = (params.get("name") or "").strip()
            image = self._get_image(image_index)
            channel = Gimp.Selection.save(image)
            if channel is None:
                return {"status": "error", "error": "Gimp.Selection.save returned None (no selection?)"}
            if name:
                try: channel.set_name(name)
                except Exception: pass
            Gimp.displays_flush()
            return {"status": "success", "results": {
                "status":  "success",
                "id":      channel.get_id(),
                "name":    channel.get_name(),
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    def _list_channels(self, params):
        """Enumerate an image's saved channels (not the built-in RGB/A ones)."""
        try:
            image_index = int(params.get("image_index", 0))
            image = self._get_image(image_index)
            channels = []
            for ch in (image.get_channels() or []):
                try:    opacity = float(ch.get_opacity())
                except Exception: opacity = None
                try:    visible = bool(ch.get_visible())
                except Exception: visible = None
                try:    color = self._color_to_hex(ch.get_color())
                except Exception: color = None
                channels.append({
                    "id":        ch.get_id(),
                    "name":      ch.get_name(),
                    "opacity":   opacity,
                    "visible":   visible,
                    "color":     color,
                })
            return {"status": "success", "results": {
                "status":   "success",
                "count":    len(channels),
                "channels": channels,
            }}
        except Exception as e:
            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


Gimp.main(MCPPlugin.__gtype__, sys.argv)
