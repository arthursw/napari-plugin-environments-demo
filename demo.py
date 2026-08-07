# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#   "imagecodecs",
#   "napari[optional,pyqt6] @ git+https://github.com/arthursw/napari.git@plugin-environments-demo-v1",
#   "napari-isolation-demo @ git+https://github.com/arthursw/napari-plugin-environments-demo.git@plugin-environments-demo-v1#subdirectory=plugins/napari-isolation-demo",
#   "napari-plugin-manager @ git+https://github.com/arthursw/napari-plugin-manager.git@plugin-environments-demo-v1",
#   "npe2 @ git+https://github.com/arthursw/npe2.git@plugin-environments-demo-v1",
#   "wetlands==2.3.3",
# ]
# ///

import napari
import numpy as np


def sample_image(size: int = 512) -> np.ndarray:
    coordinate = np.linspace(-1, 1, size, dtype=np.float32)
    yy, xx = np.meshgrid(coordinate, coordinate, indexing='ij')
    image = 0.12 * (xx + 1) + 0.08 * (yy + 1)
    for x, y, radius, intensity in (
        (-0.45, -0.35, 0.22, 0.75),
        (0.34, -0.28, 0.17, 0.62),
        (-0.10, 0.34, 0.28, 0.88),
        (0.52, 0.48, 0.13, 0.70),
    ):
        image += intensity * np.exp(
            -((xx - x) ** 2 + (yy - y) ** 2) / (2 * radius**2)
        )
    return np.clip(image, 0, 1)


viewer = napari.Viewer(title='Conflict-free napari plugins')
viewer.add_image(sample_image(), name='Synthetic cells')
napari.run()
