import numpy as np
import gpflow
import gpflowopt

import pymanopt.manifolds as pyman_man

import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from mpl_toolkits.mplot3d import Axes3D

from BoManifolds.Riemannian_utils.SPD_utils import symmetric_matrix_to_vector_mandel, \
    vector_to_symmetric_matrix_mandel, in_domain, project_to_domain
from BoManifolds.Riemannian_utils.SPD_utils_tf import symmetric_matrix_to_vector_tf

from BoManifolds.kernel_utils.kernels_spd_tf import SpdAffineInvariantGaussianKernel

from BoManifolds.BO_utils.manifold_optimization import ManifoldOptimizer
from BoManifolds.BO_utils.multistarted_optimization import MultistartedOptimizer
from BoManifolds.BO_utils.constrained_optimization import AnchorPointsGeneratorWithSpdConstraint

from BoManifolds.plot_utils.manifold_plots import plot_spd_cone
from BoManifolds.plot_utils.bo_plots import bo_plot_function_spd, bo_plot_acquisition_spd, bo_plot_gp_spd

plt.rcParams['text.usetex'] = True  # use Latex font for plots
"""
This example shows the use of Geometry-aware Bayesian optimization (GaBO) on the SPD manifold S2_++ to optimize the 
Ackley function. 

The Ackley function, defined on the tangent space of the north pole, is projected on the SPD manifold with the 
exponential map (i.e. the logarithm map is used to determine the function value). 
The search space is defined as a subspace of the SPD manifold bounded by minimum and maximum eigenvalues. These bounds 
are defined by the gpflowopt domain, as the SPD functions define the upper/lower bounds as maximum/minimum eigenvalues.
GaBO uses a Gaussian kernel with the geodesic distance. To guarantee the positive-definiteness of the kernel, the 
lengthscale beta must be above the beta min value. This value can be determined by using the example 
kernels/sphere_gaussian_kernel_parameters.py for each sphere manifold.
The acquisition function is optimized on the manifold with the constrained conjugate gradient descent method on 
Riemannian manifold. The conjugate gradient descent is originally implemented in pymanopt. A constrained version 
is used here to handle bound constraints.

The dimension of the manifold is set by the variable 'dim'. Note that the following element must be adapted when the 
dimension is modified:
- beta_min must be recomputed for the new manifold;
- the domain must be updated to have gpflowopt domain per dimension. This domain is not used in GaBO, 
    but is required by gpflowopt;
- if the dimension is not 3, 'display_figures' must be set to 'False'.
The number of BO iterations is set by the user by changing the variable 'nb_iter_bo'.

The current optimum value of the function is printed at each BO iteration and the optimal estimate of the optimizer 
(on the sphere) is printed at the end of the queries. 
The following graphs are produced by this example:
- the convergence graph shows the distance between two consecutive iterations and the best function value found by the 
    BO at each iteration. Note that the randomly generated initial data are not displayed, so that the iterations number 
    starts at the number of initial data + 1.
The following graphs are produced by this example if 'display_figures' is 'True':
- the true function graph is displayed on S2_++;
- the acquisition function at the end of the optimization is displayed on S2_++;
- the GP mean at the end of the optimization is displayed on S2_++;
- the GP mean and variances are displayed on 2D projections of S2_++;
- the BO observations are displayed on S2_++.
For all the graphs, the optimum parameter is displayed with a star, the current best estimation with a diamond and all 
the BO observation with dots.

Authors: Noemie Jaquier and Leonel Rozo, 2019
License: MIT
Contact: noemie.jaquier@idiap.ch, leonel.rozo@de.bosch.com
"""

if __name__ == "__main__":
    np.random.seed(1234)

    # Define the dimension
    # If the dimension is changed:
    # - beta min must be adapted
    # - the optimization domain must be updated as one domain per dimension is required by gpflowopt
    dim = 2

    # Define the dimension of the Mandel vector notation
    dim_vec = int(dim + dim * (dim - 1) / 2)

    # Beta min value
    beta_min = 0.5

    # True to display sphere figures (possible only if the dimension is 3 (3D graphs))
    display_figures = True

    # Number of BO iterations
    nb_iter_bo = 25

    # Instantiate the manifold
    spd_manifold = pyman_man.PositiveDefinite(dim)

    # Instantiate manifold domain functions (needed for the constrained optimization with CG on manifold)
    spd_manifold.in_domain = in_domain
    spd_manifold.project_to_domain = project_to_domain

    # Bounding eigenvalues
    min_eigenvalue = 0.001
    max_eigenvalue = 5.

    # Function to optimize
    base = np.array([[2.5, -0.7], [-0.7, 2.3]])

    # Define the function to optimize with BO
    # Must output a numpy [1,1] shaped array
    # Minus likelihood of covariance sigma for the distribution of data_test_fct (assumed centered)
    def test_function(x):
        x = vector_to_symmetric_matrix_mandel(x[0])

        x_proj = spd_manifold.log(base, x)

        # Ackley function
        a = 20
        b = 0.2
        c = 2 * np.pi
        y = -a * np.exp(-b * np.sqrt((x_proj[0, 0] ** 2 + x_proj[1, 1] ** 2 + x_proj[1, 0] ** 2) / 3.)) \
            - np.exp((np.cos(c * x_proj[0, 0]) + np.cos(c * x_proj[1, 1]) + np.cos(c * x_proj[1, 0])) / 3.) \
            + a + np.exp(1.)

        return y[None, None]

    # Optimal parameter
    true_sigma = base

    # Optimal function value
    true_opt_val = test_function(symmetric_matrix_to_vector_mandel(true_sigma)[None])[0]

    if display_figures:
        # Plot test function with inputs in the SPD manifold
        # 3D figure
        r_cone = 5.
        fig = plt.figure(figsize=(10, 10))
        ax = Axes3D(fig)
        max_colors = bo_plot_function_spd(ax, test_function, r_cone=r_cone, true_opt_x=true_sigma,
                                          true_opt_y=true_opt_val, alpha=0.25, n_elems=100, n_elems_h=10)
        ax.set_title('True function', fontsize=50)
        plt.show()

    # ### Optimization of the test function
    # Specify the optimization domain
    domain = gpflowopt.domain.ContinuousParameter('x1', min_eigenvalue, max_eigenvalue) \
             + gpflowopt.domain.ContinuousParameter('x2', min_eigenvalue, max_eigenvalue) \
             + gpflowopt.domain.ContinuousParameter('x3', -max_eigenvalue, max_eigenvalue)

    # Define SPD data generator
    # in this case, generating the anchor points with this function gives better results than using the random
    # function of the psd manifold of pymanopt (it samples for eigenvalues from 0 to 1, therefore does not cover
    # so well the domain).
    spd_random_generator = AnchorPointsGeneratorWithSpdConstraint(domain=domain, dim=dim, min_eigenvalue=0.1,
                                                                  max_eigenvalue=max_eigenvalue)
    # Generate random data in the SPD cone
    nb_data_init = 5
    x_init_vec = spd_random_generator.generate_samples(nb_samples=nb_data_init)
    y_init = np.zeros((nb_data_init, 1))
    for n in range(nb_data_init):
        y_init[n] = test_function(x_init_vec[n][None])

    # Create gpflow model
    # As the kernel take vectors as inputs, we give the vector dimension
    k = SpdAffineInvariantGaussianKernel(input_dim=dim_vec, active_dims=range(dim_vec), beta=1.0, variance=1.,
                                         beta_min=beta_min)
    # Constant mean function.
    mean_fct = gpflow.mean_functions.Constant(25.)
    model = gpflow.gpr.GPR(x_init_vec, y_init, kern=k, mean_function=mean_fct)

    # Define the acquisition function
    acq_fct = gpflowopt.acquisition.ExpectedImprovement(model=model)

    # Optimizers using Pymanopt
    acq_fct_opt = MultistartedOptimizer(domain, ManifoldOptimizer(domain=domain, manifold=spd_manifold,
                                                                  manifold_dim=dim, matrix_manifold_dim=dim,
                                                                  matrix_to_vector_transform=
                                                                  symmetric_matrix_to_vector_mandel,
                                                                  vector_to_matrix_transform=
                                                                  vector_to_symmetric_matrix_mandel,
                                                                  matrix_to_vector_transform_tf=
                                                                  symmetric_matrix_to_vector_tf,
                                                                  solver_type='BoundConstrainedConjugateGradient'),
                                        spd_random_generator)

    # ### Bayesian optimization
    # Define the Bayesian optimization
    # An optimizer for the acquisition function can additionally be specified with the "optimizer" parameter
    bo_optimizer = gpflowopt.bo.BayesianOptimizer(domain=domain, acquisition=acq_fct, optimizer=acq_fct_opt,
                                                  scaling=False, verbose=True)

    # Run the Bayessian optimization
    Bopt = bo_optimizer.optimize(test_function, n_iter=nb_iter_bo)
    print(Bopt)

    if display_figures:
        # Plot the acquisition function
        fig = plt.figure(figsize=(10, 10))
        ax = Axes3D(fig)
        bo_plot_acquisition_spd(ax, acq_fct, r_cone=r_cone, xs=bo_optimizer.acquisition.data[0], opt_x=Bopt.x,
                                true_opt_x=symmetric_matrix_to_vector_mandel(true_sigma)[None], n_elems=20,
                                n_elems_h=10)
        ax.set_title('Acquisition function', fontsize=50)
        plt.show()

        # Plot the GP
        fig = plt.figure(figsize=(10, 10))
        ax = Axes3D(fig)
        bo_plot_gp_spd(ax, model, r_cone=r_cone, xs=bo_optimizer.acquisition.data[0], opt_x=Bopt.x,
                       true_opt_x=symmetric_matrix_to_vector_mandel(true_sigma)[None], true_opt_y=true_opt_val,
                       max_colors=25., n_elems=20, n_elems_h=10)
        ax.set_title('GP mean', fontsize=50)
        plt.show()

    if display_figures:
        # Plot test function with SPD inputs
        # 3D figure
        fig = plt.figure(figsize=(5, 5))
        ax = Axes3D(fig)
        # Make the panes transparent
        ax.xaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.yaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.zaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        # Make the grid lines transparent
        ax.xaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)
        ax.yaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)
        ax.zaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)
        # Remove axis
        ax._axis3don = False
        # Initial view
        ax.view_init(elev=10, azim=-20.)  # (default: elev=30, azim=-60)
        # Plot SPD cone
        plot_spd_cone(ax, r=r_cone, lim_fact=0.8)
        # Plot evaluated points
        x_eval = bo_optimizer.acquisition.data[0]
        y_eval = bo_optimizer.acquisition.data[1]
        for n in range(x_eval.shape[0]):
            ax.scatter(x_eval[n, 0], x_eval[n, 1], x_eval[n, 2] / np.sqrt(2),
                       c=pl.cm.inferno(1. - (y_eval[n] - true_opt_val) / max_colors))
        # Plot true minimum
        ax.scatter(true_sigma[0, 0], true_sigma[1, 1], true_sigma[0, 1], s=40, c='g', marker='P')
        # Plot BO minimum
        ax.scatter(Bopt.x[0, 0], Bopt.x[0, 1], Bopt.x[0, 2] / np.sqrt(2), s=20, c='r', marker='D')
        ax.set_title('BO observations', fontsize=30)
        plt.show()

    # Convergence plots
    # Compute distances between consecutive x's
    nb_eval = x_eval.shape[0]
    distances = np.zeros(nb_eval - 1)
    for n in range(nb_eval - 1):
        distances[n] = spd_manifold.dist(vector_to_symmetric_matrix_mandel(x_eval[n + 1, :]),
                                         vector_to_symmetric_matrix_mandel(x_eval[n, :]))
    # Compute best evaluation for each iteration
    y_best = np.ones(nb_eval)
    for i in range(nb_eval):
        y_best[i] = y_eval[:(i + 1)].min()

    #  Plot distances between consecutive x's
    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    plt.plot(np.array(range(nb_data_init, nb_eval - 1)), distances[nb_data_init:], '-ro')
    plt.xlabel('Iteration', fontsize=18)
    plt.ylabel('d(x[n], x[n-1])', fontsize=18)
    plt.title('Distance between consecutive observations', fontsize=20)
    plt.grid(True)
    plt.tick_params(axis='both', which='major', labelsize=14)
    # Plot best estimation at each iteration
    plt.subplot(1, 2, 2)
    plt.plot(np.array(range(nb_data_init, nb_eval)), y_best[nb_data_init:], '-o')
    plt.xlabel('Iteration', fontsize=18)
    plt.ylabel('Best y', fontsize=18)
    plt.title('Value of the best selected sample', fontsize=20)
    plt.grid(True)
    plt.tick_params(axis='both', which='major', labelsize=14)
    plt.show()
