"""Sound effects and background music for Block Blitz."""
from pathlib import Path

import pygame

# Build paths from this file's folder, so sounds load no matter which
# folder you run the game from (VS Code sometimes runs from a different one).
SOUND_DIR = Path(__file__).resolve().parent / "sound"


class Music:
    def __init__(self):
        self.is_playing = False
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(SOUND_DIR / "music.ogg"))
        self.rotate_sound = pygame.mixer.Sound(str(SOUND_DIR / "rotate.ogg"))
        self.clear_sound_effect = pygame.mixer.Sound(str(SOUND_DIR / "clear.ogg"))
        self.collision_sound_effect = pygame.mixer.Sound(str(SOUND_DIR / "collision.ogg"))
        self.game_over_sound_effect = pygame.mixer.Sound(str(SOUND_DIR / "gameover.ogg"))

        # default volumes (0.0 - 1.0)
        self.music_volume = 0.5
        self.rotate_volume = 0.5
        self.clear_volume = 0.5
        self.collision_volume = 0.5
        self.game_over_volume = 0.5

    # ---------- volume setters
    def set_music_volume(self, volume):
        self.music_volume = volume
        pygame.mixer.music.set_volume(volume)

    def set_rotate_volume(self, volume):
        self.rotate_volume = volume

    def set_clear_volume(self, volume):
        self.clear_volume = volume

    def set_collision_volume(self, volume):
        self.collision_volume = volume

    def set_game_over_volume(self, volume):
        self.game_over_volume = volume

    # ---------- music
    def play_music(self):
        if not self.is_playing:
            pygame.mixer.music.play(-1)
            pygame.mixer.music.set_volume(self.music_volume)
            self.is_playing = True

    def stop_music(self):
        pygame.mixer.music.stop()
        self.is_playing = False

    def pause_music(self):
        pygame.mixer.music.pause()

    def resume_music(self):
        pygame.mixer.music.unpause()

    # ---------- effects
    def rotation_sound(self):
        self.rotate_sound.set_volume(self.rotate_volume)
        self.rotate_sound.play()

    def clear_sound(self, lines_cleared):
        if lines_cleared > 0:
            # a little louder for bigger clears
            volume = min(1.0, self.clear_volume * (0.7 + 0.1 * lines_cleared))
            self.clear_sound_effect.set_volume(volume)
            self.clear_sound_effect.play()

    def collision_sound(self):
        self.collision_sound_effect.set_volume(self.collision_volume)
        self.collision_sound_effect.play()

    def game_over_sound(self):
        self.stop_music()
        # the old version used the collision volume here, so it was too quiet
        self.game_over_sound_effect.set_volume(self.game_over_volume)
        self.game_over_sound_effect.play()
