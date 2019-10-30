import numpy as np

'''
Authors: Noemie Jaquier and Leonel Rozo, 2019
License: MIT
Contact: noemie.jaquier@idiap.ch, leonel.rozo@de.bosch.com
'''


def rotation_matrix_from_axis_angle(ax, angle):
    """
    Gets rotation matrix from axis angle representation using Rodriguez formula.
    Based on the function of riepybdlib (https://gitlab.martijnzeestraten.nl/martijn/riepybdlib)

    Parameters
    ----------
    :param ax: unit axis defining the axis of rotation
    :param angle: angle of rotation

    Returns
    -------
    :return: R(ax, angle) = I + sin(angle) x ax + (1 - cos(angle) ) x ax^2 with x the cross product.
    """
    utilde = vector_to_skew_matrix(ax)
    return np.eye(3) + np.sin(angle)*utilde + (1 - np.cos(angle))*utilde.dot(utilde)


def vector_to_skew_matrix(q):
    """
    Transform a vector into a skew-symmetric matrix

    Parameters
    ----------
    :param q: vector

    Returns
    -------
    :return: corresponding skew-symmetric matrix
    """
    return np.array([[0, -q[2], q[1]], [q[2], 0, -q[0]], [-q[1], q[0], 0]])