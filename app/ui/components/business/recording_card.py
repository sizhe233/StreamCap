import asyncio
import os.path

import flet as ft

from ....models.recording.recording_model import Recording
from ....models.recording.recording_status_model import RecordingStatus
from ....utils import utils
from ....utils.logger import logger
from ...views.storage_view import StoragePage
from ..dialogs.card_dialog import CardDialog
from ..state.recording_card_state import RecordingCardState
from .recording_dialog import RecordingDialog
from .video_player import VideoPlayer


class RecordingCardManager:
    def __init__(self, app):
        self.app = app
        self.cards_obj = {}
        self.update_duration_tasks = {}
        self.selected_cards = {}
        self.app.language_manager.add_observer(self)
        self._ = {}
        self.load()
        self.pubsub_subscribe()

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_card", "recording_manager", "base", "recordings_page", "video_quality", "storage_page"):
            self._.update(language.get(key, {}))

    def pubsub_subscribe(self):
        self.app.page.pubsub.subscribe_topic("update", self.subscribe_update_card)
        self.app.page.pubsub.subscribe_topic("delete", self.subscribe_remove_cards)

    async def create_card(self, recording: Recording):
        """Create a card for a given recording."""
        rec_id = recording.rec_id
        
        # 检查页面连接状态
        if not self._is_page_connected():
            logger.warning(f"Page disconnected, cannot create card for: {rec_id}")
            return None
            
        if not self.cards_obj.get(rec_id):
            if self.app.recording_enabled:
                self.app.page.run_task(self.app.record_manager.check_if_live, recording)
            else:
                recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                
        try:
            card_data = self._create_card_components(recording)
            
            # 验证卡片组件是否正确创建
            if not card_data or not card_data.get("card"):
                logger.error(f"Failed to create card components for: {rec_id}")
                return None
                
            # 确保卡片被正确添加到页面，以便获得有效的UID
            card = card_data["card"]
            
            # 将卡片数据存储到管理器中
            self.cards_obj[rec_id] = card_data
            
            # 启动更新任务
            self.start_update_task(recording)
            
            logger.debug(f"Successfully created card for: {rec_id}")
            return card
            
        except Exception as e:
            logger.error(f"Error creating card for {rec_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _create_card_components(self, recording: Recording):
        """create card components."""
        speed = recording.speed
        duration_text_label = ft.Text(self.app.record_manager.get_duration(recording), size=12)

        record_button = ft.IconButton(
            icon=self.get_icon_for_recording_state(recording),
            tooltip=self.get_tip_for_recording_state(recording),
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_button_on_click, e, rec),
        )

        edit_button = ft.IconButton(
            icon=ft.Icons.EDIT,
            tooltip=self._["edit_record_config"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.edit_recording_button_click, e, rec),
        )

        preview_button = ft.IconButton(
            icon=ft.Icons.VIDEO_LIBRARY,
            tooltip=self._["preview_video"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.preview_video_button_on_click, e, rec),
        )

        monitor_button = ft.IconButton(
            icon=self.get_icon_for_monitor_state(recording),
            tooltip=self.get_tip_for_monitor_state(recording),
            on_click=lambda e, rec=recording: self.app.page.run_task(self.monitor_button_on_click, e, rec),
        )

        delete_button = ft.IconButton(
            icon=ft.Icons.DELETE,
            tooltip=self._["delete_monitor"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_delete_button_click, e, rec),
        )

        display_title = RecordingCardState.get_display_title(recording, self._)
        display_title_label = ft.Text(
            display_title,
            size=14,
            selectable=True,
            max_lines=1,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
            weight=RecordingCardState.get_title_weight(recording),
        )

        open_folder_button = ft.IconButton(
            icon=ft.Icons.FOLDER,
            tooltip=self._["open_folder"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_dir_button_on_click, e, rec),
        )
        recording_info_button = ft.IconButton(
            icon=ft.Icons.INFO,
            tooltip=self._["recording_info"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_info_button_on_click, e, rec),
        )
        speed_text_label = ft.Text(speed, size=12)

        status_label = self.create_status_label(recording)

        title_row = ft.Row(
            [display_title_label, status_label] if status_label else [display_title_label],
            alignment=ft.MainAxisAlignment.START,
            spacing=5,
            tight=True,
        )

        card_container = ft.Container(
            content=ft.Column(
                [
                    title_row,
                    duration_text_label,
                    speed_text_label,
                    ft.Row(
                        [
                            record_button,
                            open_folder_button,
                            recording_info_button,
                            preview_button,
                            edit_button,
                            delete_button,
                            monitor_button
                        ],
                        spacing=3,
                        alignment=ft.MainAxisAlignment.START,
                        scroll=ft.ScrollMode.HIDDEN
                    ),
                ],
                spacing=3,
                tight=True
            ),
            padding=8,
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_card_on_click, e, rec),
            bgcolor=self.get_card_background_color(recording),
            border_radius=5,
            border=ft.border.all(2, self.get_card_border_color(recording)),
        )
        card = ft.Card(key=str(recording.rec_id), content=card_container)

        return {
            "card": card,
            "display_title_label": display_title_label,
            "duration_label": duration_text_label,
            "speed_label": speed_text_label,
            "record_button": record_button,
            "open_folder_button": open_folder_button,
            "recording_info_button": recording_info_button,
            "edit_button": edit_button,
            "monitor_button": monitor_button,
            "status_label": status_label,
        }

    def get_card_background_color(self, recording: Recording):
        is_dark_mode = self.app.page.theme_mode == ft.ThemeMode.DARK
        if recording.selected:
            return ft.Colors.GREY_800 if is_dark_mode else ft.Colors.GREY_400
        return None

    @staticmethod
    def get_card_border_color(recording: Recording):
        """Get the border color of the card."""
        return RecordingCardState.get_border_color(recording)

    def create_status_label(self, recording: Recording):
        config = RecordingCardState.get_status_label_config(recording, self._)
        if not config:
            return None

        return ft.Container(
            content=ft.Text(
                config["text"],
                color=config["text_color"],
                size=12,
                weight=ft.FontWeight.BOLD
            ),
            bgcolor=config["bgcolor"],
            border_radius=5,
            padding=5,
            width=60,
            height=26,
            alignment=ft.alignment.center,
        )

    async def update_card(self, recording):
        """Update only the recordings cards in the scrollable content area."""
        # Early check for page connection
        if not self._is_page_connected():
            logger.debug(f"Page disconnected, skipping card update for: {recording.rec_id}")
            return
            
        if recording.rec_id not in self.cards_obj:
            logger.debug(f"Card not found for recording: {recording.rec_id}")
            return
            
        try:
            recording_card = self.cards_obj[recording.rec_id]
            
            # Check if card object is valid
            if not recording_card or not recording_card.get("card"):
                logger.warning(f"Invalid card object for recording: {recording.rec_id}")
                return

            # Update display title
            display_title = RecordingCardState.get_display_title(recording, self._)
            if recording_card.get("display_title_label"):
                recording_card["display_title_label"].value = display_title
                recording_card["display_title_label"].weight = RecordingCardState.get_title_weight(recording)

            # Update status label with enhanced error handling
            new_status_label = self.create_status_label(recording)
            if recording_card["card"] and recording_card["card"].content and recording_card["card"].content.content:
                try:
                    title_row = recording_card["card"].content.content.controls[0]
                    title_row.alignment = ft.MainAxisAlignment.START
                    title_row.spacing = 5
                    title_row.tight = True

                    # Update the status label if it exists
                    if new_status_label:
                        if len(title_row.controls) > 1:
                            title_row.controls[1] = new_status_label
                        else:
                            title_row.controls.append(new_status_label)
                    else:
                        if len(title_row.controls) > 1:
                            title_row.controls.pop()
                except (IndexError, AttributeError) as e:
                    logger.warning(f"Failed to update status label for card {recording.rec_id}: {e}")

            # Update duration and speed
            if recording_card.get("duration_label"):
                recording_card["duration_label"].value = self.app.record_manager.get_duration(recording)

            if recording_card.get("speed_label"):
                recording_card["speed_label"].value = recording.speed

            # Update buttons
            if recording_card.get("record_button"):
                recording_card["record_button"].icon = self.get_icon_for_recording_state(recording)
                recording_card["record_button"].tooltip = self.get_tip_for_recording_state(recording)

            if recording_card.get("monitor_button"):
                recording_card["monitor_button"].icon = self.get_icon_for_monitor_state(recording)
                recording_card["monitor_button"].tooltip = self.get_tip_for_monitor_state(recording)

            # Update card appearance
            if recording_card["card"] and recording_card["card"].content:
                recording_card["card"].content.bgcolor = self.get_card_background_color(recording)
                recording_card["card"].content.border = ft.border.all(2, self.get_card_border_color(recording))
                
                # Final page update with enhanced error handling
                if self._is_page_connected():
                    try:
                        # Check if control UID is valid
                        card = recording_card["card"]
                        if hasattr(card, '_Control__uid') and card._Control__uid is None:
                            logger.warning(f"Card UID is None for {recording.rec_id}, skipping update")
                            return
                            
                        self.app.page.update()
                        # 只在录制状态变化时记录日志，避免频繁输出
                        # if recording.is_recording or recording.status_info in [RecordingStatus.RECORDING_ERROR, RecordingStatus.RECORDING]:
                            # logger.debug(f"Updated card for: {recording.rec_id} - Status: {recording.status_info}")
                    except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                        logger.debug(f"Page disconnected during update: {e}")
                        return
                    except Exception as e:
                        logger.warning(f"Unexpected error during page update for {recording.rec_id}: {e}")
                        return
                else:
                    logger.debug(f"Page disconnected before final update for: {recording.rec_id}")
                    return

        except (ft.core.page.PageDisconnectedException, AssertionError) as e:
            logger.debug(f"Page disconnected during card update: {e}")
            return
        except Exception as e:
            logger.error(f"Unexpected error updating card for {recording.rec_id}: {e}")

    def _is_page_connected(self) -> bool:
        """Check if the page is still connected and responsive"""
        try:
            if not (hasattr(self.app, 'page') and 
                    self.app.page is not None and 
                    hasattr(self.app.page, 'update')):
                return False
                
            # Check if page is disconnected
            if getattr(self.app.page, '_disconnected', False):
                return False
                
            # Additional check for web pages that might be frozen
            if hasattr(self.app.page, 'web') and self.app.page.web:
                # For web pages, we assume they might be frozen if they've been inactive
                # We'll rely on timeouts in calling code to handle frozen pages
                return True
                
            return True
        except Exception as e:
            logger.debug(f"Page connection check failed: {e}")
            return False

    async def update_monitor_state(self, recording: Recording):
        """Update the monitor button state based on the current monitoring status."""
        if recording.monitor_status:
            recording.update(
                {
                    "recording": False,
                    "monitor_status": not recording.monitor_status,
                    "status_info": RecordingStatus.STOPPED_MONITORING,
                    "display_title": f"[{self._['monitor_stopped']}] {recording.title}",
                }
            )
            self.app.record_manager.stop_recording(recording, manually_stopped=True)
            self.app.page.run_task(self.app.snack_bar.show_snack_bar, self._["stop_monitor_tip"])
        else:
            recording.update(
                {
                    "monitor_status": not recording.monitor_status,
                    "status_info": RecordingStatus.MONITORING,
                    "display_title": f"{recording.title}",
                }
            )
            self.app.page.run_task(self.app.record_manager.check_if_live, recording)
            self.app.page.run_task(self.app.snack_bar.show_snack_bar, self._["start_monitor_tip"], ft.Colors.GREEN)

        await self.update_card(recording)
        self.app.page.pubsub.send_others_on_topic("update", recording)
        self.app.page.run_task(self.app.record_manager.persist_recordings)

    async def show_recording_info_dialog(self, recording: Recording):
        """Display a dialog with detailed information about the recording."""
        try:
            dialog = CardDialog(self.app, recording)
            dialog.open = True
            self.app.dialog_area.content = dialog
            try:
                self.app.page.update()
            except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update recording info dialog failed: {e}")
        except (ft.core.page.PageDisconnectedException, AssertionError) as e:
            logger.debug(f"Show recording info dialog failed: {e}")
        except Exception as e:
            logger.debug(f"Show recording info dialog failed: {e}")

    async def edit_recording_callback(self, recording_list: list[dict]):
        recording_dict = recording_list[0]
        rec_id = recording_dict["rec_id"]
        recording = self.app.record_manager.find_recording_by_id(rec_id)

        await self.app.record_manager.update_recording_card(recording, updated_info=recording_dict)
        if not recording_dict["monitor_status"]:
            recording.display_title = f"[{self._['monitor_stopped']}] " + recording.title

        recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
            recording.scheduled_start_time, recording.monitor_hours)

        await self.update_card(recording)
        self.app.page.pubsub.send_others_on_topic("update", recording_dict)

    async def on_toggle_recording(self, recording: Recording):
        """Toggle the recording state for a specific recording."""
        if recording and self.app.recording_enabled:
            if recording.is_recording:
                self.app.record_manager.stop_recording(recording, manually_stopped=True)
                await self.app.snack_bar.show_snack_bar(self._["stop_record_tip"])
            else:
                if recording.monitor_status:
                    await self.app.record_manager.check_if_live(recording)
                    if recording.is_live:
                        self.app.record_manager.start_update(recording)
                        await self.app.snack_bar.show_snack_bar(self._["pre_record_tip"], bgcolor=ft.Colors.GREEN)
                    else:
                        await self.app.snack_bar.show_snack_bar(self._["is_not_live_tip"])
                else:
                    await self.app.snack_bar.show_snack_bar(self._["please_start_monitor_tip"])

            await self.update_card(recording)
            self.app.page.pubsub.send_others_on_topic("update", recording)

    async def on_delete_recording(self, recording: Recording):
        """Delete a recording from the list and update UI."""
        if recording:
            if recording.is_recording:
                await self.app.snack_bar.show_snack_bar(self._["please_stop_monitor_tip"])
                return
            await self.app.record_manager.delete_recording_cards([recording])
            await self.app.snack_bar.show_snack_bar(
                self._["delete_recording_success_tip"], bgcolor=ft.Colors.GREEN, duration=2000
            )

    async def remove_recording_card(self, recordings: list[Recording]):
        try:
            recordings_page = self.app.current_page
            if not recordings_page or not hasattr(recordings_page, 'recording_card_area'):
                logger.warning("Recording page or card area not available")
                return

            existing_ids = {rec.rec_id for rec in self.app.record_manager.recordings}
            remove_ids = {rec.rec_id for rec in recordings}
            keep_ids = existing_ids - remove_ids

            # Find cards to remove
            cards_to_remove = []
            for rec_id, card_data in self.cards_obj.items():
                if rec_id not in keep_ids:
                    cards_to_remove.append(card_data["card"])
                    # 不记录标记移除的详细信息，减少日志噪音

            # Remove cards from UI
            if hasattr(recordings_page.recording_card_area, 'content') and hasattr(recordings_page.recording_card_area.content, 'controls'):
                original_count = len(recordings_page.recording_card_area.content.controls)
                recordings_page.recording_card_area.content.controls = [
                    control
                    for control in recordings_page.recording_card_area.content.controls
                    if control not in cards_to_remove
                ]
                new_count = len(recordings_page.recording_card_area.content.controls)
                # 只在实际移除卡片时记录
                if original_count != new_count:
                    logger.info(f"Removed {original_count - new_count} cards from UI")

            # Clean up cards_obj
            original_cards_count = len(self.cards_obj)
            self.cards_obj = {
                k: v for k, v in self.cards_obj.items()
                if k in keep_ids
            }
            new_cards_count = len(self.cards_obj)
            # 只在实际清理对象时记录
            if original_cards_count != new_cards_count:
                logger.info(f"Cleaned up {original_cards_count - new_cards_count} card objects")

            # Stop update tasks for removed cards
            for rec_id in remove_ids:
                if rec_id in self.update_duration_tasks:
                    try:
                        self.update_duration_tasks[rec_id].cancel()
                        del self.update_duration_tasks[rec_id]
                        logger.debug(f"Cancelled update task for: {rec_id}")
                    except Exception as e:
                        logger.debug(f"Failed to cancel update task for {rec_id}: {e}")

            # Update UI with timeout protection
            if self._is_page_connected():
                try:
                    # Use asyncio.wait_for to prevent hanging on frozen pages
                    await asyncio.wait_for(
                        asyncio.to_thread(recordings_page.recording_card_area.update),
                        timeout=3.0
                    )
                    # 不记录成功的卡片区域更新，减少日志噪音
                    pass
                except asyncio.TimeoutError:
                    logger.warning("Recording card area update timed out (page may be frozen)")
                except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                    logger.debug(f"Page disconnected during card area update: {e}")
                except Exception as e:
                    logger.warning(f"Failed to update recording card area: {e}")
            else:
                logger.debug("Page disconnected, skipping card area update")

        except (ft.core.page.PageDisconnectedException, AssertionError) as e:
            logger.debug(f"Remove recording card failed: {e}")
        except Exception as e:
            logger.error(f"Remove recording card failed: {e}")
            raise

    @staticmethod
    async def update_record_hover(recording: Recording):
        return ft.Colors.GREY_400 if recording.selected else None

    @staticmethod
    def get_icon_for_recording_state(recording: Recording):
        """Return the appropriate icon based on the recording's state."""
        return RecordingCardState.get_recording_icon(recording)

    def get_tip_for_recording_state(self, recording: Recording):
        return self._["stop_record"] if recording.is_recording else self._["start_record"]

    @staticmethod
    def get_icon_for_monitor_state(recording: Recording):
        """Return the appropriate icon based on the monitor's state."""
        return RecordingCardState.get_monitor_icon(recording)

    def get_tip_for_monitor_state(self, recording: Recording):
        return self._["stop_monitor"] if recording.monitor_status else self._["start_monitor"]

    async def update_duration(self, recording: Recording):
        """Update the duration text periodically."""
        while True:
            update_interval = 1
            await asyncio.sleep(update_interval)
            
            # Check if we should stop the task
            if not recording or recording.rec_id not in self.cards_obj:
                logger.debug(f"Stopping duration update task for removed recording: {recording.rec_id if recording else 'None'}")
                break
                
            # Check page connection
            if not self._is_page_connected():
                logger.debug(f"Page disconnected, stopping duration update for: {recording.rec_id}")
                break

            if recording.is_recording:
                try:
                    duration_label = self.cards_obj[recording.rec_id]["duration_label"]
                    duration_label.value = self.app.record_manager.get_duration(recording)
                    
                    # Only update if page is still connected
                    if self._is_page_connected():
                        duration_label.update()
                    else:
                        logger.debug(f"Page disconnected during duration update for: {recording.rec_id}")
                        break
                        
                except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                    logger.debug(f"Page disconnected during duration update: {e}")
                    break
                except Exception as e:
                    logger.debug(f"Unexpected error updating duration for {recording.rec_id}: {e}")
                    # Don't break on unexpected errors, just log and continue

    def start_update_task(self, recording: Recording):
        """Start a background task to update the duration text."""
        self.update_duration_tasks[recording.rec_id] = self.app.page.run_task(self.update_duration, recording)

    async def on_card_click(self, recording: Recording):
        """Handle card click events."""
        if not self._is_page_connected():
            logger.debug(f"Page disconnected, skipping card click for: {recording.rec_id}")
            return
            
        try:
            recording.selected = not recording.selected
            self.selected_cards[recording.rec_id] = recording
            self.cards_obj[recording.rec_id]["card"].content.bgcolor = await self.update_record_hover(recording)
            
            if self._is_page_connected():
                try:
                    self.cards_obj[recording.rec_id]["card"].update()
                    # 不记录成功的点击状态更新，减少日志噪音
                    pass
                except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                    logger.debug(f"Page disconnected during card click update: {e}")
            else:
                logger.debug(f"Page disconnected before card click update for: {recording.rec_id}")
                
        except (ft.core.page.PageDisconnectedException, AssertionError) as e:
            logger.debug(f"Page disconnected during card click handling: {e}")
        except Exception as e:
            logger.error(f"Unexpected error handling card click for {recording.rec_id}: {e}")

    async def recording_dir_on_click(self, recording: Recording):
        if recording.recording_dir:
            if os.path.exists(recording.recording_dir):
                if not utils.open_folder(recording.recording_dir):
                    await self.app.snack_bar.show_snack_bar(self._['no_video_file'])
            else:
                await self.app.snack_bar.show_snack_bar(self._["no_recording_folder"])

    async def edit_recording_button_click(self, _, recording: Recording):
        """Handle edit button click by showing the edit dialog with existing recording info."""

        if recording.is_recording or recording.monitor_status:
            await self.app.snack_bar.show_snack_bar(self._["please_stop_monitor_tip"])
            return

        await RecordingDialog(
            self.app,
            on_confirm_callback=self.edit_recording_callback,
            recording=recording,
        ).show_dialog()

    async def recording_delete_button_click(self, _, recording: Recording):
        try:
            async def confirm_dlg(_):
                self.app.page.run_task(self.on_delete_recording, recording)
                await close_dialog(None)

            async def close_dialog(_):
                try:
                    delete_alert_dialog.open = False
                    delete_alert_dialog.update()
                except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                    logger.debug(f"Close delete dialog failed: {e}")

            delete_alert_dialog = ft.AlertDialog(
                title=ft.Text(self._["confirm"]),
                content=ft.Text(self._["delete_confirm_tip"]),
                actions=[
                    ft.TextButton(text=self._["cancel"], on_click=close_dialog),
                    ft.TextButton(text=self._["sure"], on_click=confirm_dlg),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                modal=False,
            )
            delete_alert_dialog.open = True
            self.app.dialog_area.content = delete_alert_dialog
            try:
                self.app.page.update()
            except (ft.core.page.PageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update delete dialog failed: {e}")
        except (ft.core.page.PageDisconnectedException, AssertionError) as e:
            logger.debug(f"Show delete dialog failed: {e}")
        except Exception as e:
            logger.debug(f"Show delete dialog failed: {e}")

    async def preview_video_button_on_click(self, _, recording: Recording):
        if self.app.page.web and recording.record_url:
            video_player = VideoPlayer(self.app)
            await video_player.preview_video(recording.preview_url, is_file_path=False, room_url=recording.url)
        elif recording.recording_dir and os.path.exists(recording.recording_dir):
            video_files = []
            for root, _, files in os.walk(recording.recording_dir):
                for file in files:
                    if utils.is_valid_video_file(file):
                        video_files.append(os.path.join(root, file))

            if video_files:
                video_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                latest_video = video_files[0]
                await StoragePage(self.app).preview_file(latest_video, recording.url)
            else:
                await self.app.snack_bar.show_snack_bar(self._["no_video_file"])
        else:
            await self.app.snack_bar.show_snack_bar(self._["no_recording_folder"])

    async def recording_button_on_click(self, _, recording: Recording):
        await self.on_toggle_recording(recording)

    async def recording_dir_button_on_click(self, _, recording: Recording):
        await self.recording_dir_on_click(recording)

    async def recording_info_button_on_click(self, _, recording: Recording):
        await self.show_recording_info_dialog(recording)

    async def monitor_button_on_click(self, _, recording: Recording):
        await self.update_monitor_state(recording)

    async def recording_card_on_click(self, _, recording: Recording):
        await self.on_card_click(recording)

    async def subscribe_update_card(self, _, recording: Recording):
        await self.update_card(recording)

    async def subscribe_remove_cards(self, _, recordings: list[Recording]):
        await self.remove_recording_card(recordings)