"""Float DST Poisson solver adapted from PIE-torch (MIT).
Copyright (c) 2022 Matthew Baugh. See LICENSE.txt and provenance.json.
Adaptation: extract the DST function; use AURA NumPy adapters without SciPy.
"""
from typing import Optional
import numpy as np
from . import fft_adapter as scipy
from .fft_adapter import ndimage

def blend_dst_numpy(target: np.ndarray, source: np.ndarray, mask: np.ndarray, corner_coord: np.ndarray,
                    mix_gradients: bool, channels_dim: Optional[int] = None):

    num_dims = len(target.shape)
    if channels_dim is not None:
        channels_dim %= num_dims    # Determine dimensions to operate on
    chosen_dimensions = [d for d in range(num_dims) if d != channels_dim]
    corner_dict = dict(zip(chosen_dimensions, corner_coord))

    result = target.copy()
    target = target[tuple([slice(corner_dict[i], corner_dict[i] + s_s) if i in chosen_dimensions else slice(None)
                           for i, s_s in enumerate(source.shape)])]

    # Zero edges of mask, to avoid artefacts
    for d in range(len(mask.shape)):
        mask[tuple([[0, -1] if i == d else slice(s) for i, s in enumerate(mask.shape)])] = 0

    # Compute gradients
    grad_kernel_1 = np.array([0, -1, 1])
    target_grads = [ndimage.correlate1d(target, grad_kernel_1, axis=d, mode='mirror') for d in chosen_dimensions]
    source_grads = [ndimage.correlate1d(source, grad_kernel_1, axis=d, mode='mirror') for d in chosen_dimensions]

    # Blend gradients, MIXING IS DONE AT INDIVIDUAL DIMENSION LEVEL!
    if mix_gradients:
        source_grads = [np.where(np.abs(t_g) >= np.abs(s_g), t_g, s_g)
                        for t_g, s_g in zip(target_grads, source_grads)]

    if channels_dim is not None:
        mask = np.expand_dims(mask, channels_dim)

    blended_grads = [t_g * (1 - mask) + s_g * mask for t_g, s_g in zip(target_grads, source_grads)]

    # Compute laplacian
    grad_kernel_2 = np.array([-1, 1, 0])
    laplacian = sum([ndimage.correlate1d(grad, grad_kernel_2, axis=grad_dim, mode='mirror')
                     for grad, grad_dim in zip(blended_grads, chosen_dimensions)])

    boundary_points = target.copy()
    # Zero all pixels except boundaries
    boundary_points[tuple([slice(1, s - 1) if i in chosen_dimensions else slice(None)
                           for i, s in enumerate(boundary_points.shape)])] = 0
    # Compute laplacian for boundaries
    lap_kernel = np.zeros([3 if i in chosen_dimensions else 1 for i in range(num_dims)])
    k_centre = [1 if i in chosen_dimensions else 0 for i in range(num_dims)]
    lap_kernel[tuple(k_centre)] = -2 * len(chosen_dimensions)
    for c_d in chosen_dimensions:
        for c_c in [0, 2]:
            lap_kernel[tuple([c_c if i == c_d else k for i, k in enumerate(k_centre)])] = 1

    boundary_points = ndimage.correlate(boundary_points, lap_kernel, mode='mirror')
    # boundary_points = sum([np.gradient(g, axis=i)
    #                        for i, g in zip(chosen_dimensions, np.gradient(boundary_points, axis=chosen_dimensions))])

    # Subtract boundary's influence from laplacian
    mod_diff = laplacian - boundary_points
    mod_diff = mod_diff[tuple([slice(1, -1) if i in chosen_dimensions else slice(None)
                               for i, s in enumerate(mod_diff.shape)])]

    # I identified the dst type as both reference implementations implement the DST via a DFFT, and the matlab code
    # implementation of the inverse also matches the inverse formulation for type 1.
    transformed = scipy.fft.dstn(mod_diff, type=1, axes=chosen_dimensions)

    eigenvalues = [2 * np.cos(np.pi * (np.arange(mod_diff.shape[i]) + 1) / (target.shape[i] - 1)) - 2
                   for i in chosen_dimensions]

    denorm = sum([e.reshape(tuple([-1 if j == i else 1 for j in range(num_dims)]))
                  for i, e in zip(chosen_dimensions, eigenvalues)])
    transformed /= denorm

    blended = scipy.fft.idstn(transformed, type=1, axes=chosen_dimensions)

    res_indices = tuple([slice(corner_dict[i] + 1, corner_dict[i] + 1 + s_s) if i in chosen_dimensions else slice(None)
                         for i, s_s in enumerate(blended.shape)])
    result[res_indices] = blended
    return result
