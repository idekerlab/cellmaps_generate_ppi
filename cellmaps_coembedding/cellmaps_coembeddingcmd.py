#! /usr/bin/env python

import argparse
import os
import sys
import logging
import logging.config

from cellmaps_coembedding.exceptions import CellmapsCoEmbeddingError
from cellmaps_utils import logutils
from cellmaps_utils import constants
import cellmaps_coembedding
from cellmaps_coembedding.runner import AutoCoEmbeddingGenerator
from cellmaps_coembedding.runner import MuseCoEmbeddingGenerator
from cellmaps_coembedding.runner import FakeCoEmbeddingGenerator
from cellmaps_coembedding.runner import CellmapsCoEmbedder

logger = logging.getLogger(__name__)

PPI_EMBEDDINGDIR = '--ppi_embeddingdir'
IMAGE_EMBEDDINGDIR = '--image_embeddingdir'


def _parse_arguments(desc, args):
    """
    Parses command line arguments

    :param desc: description to display on command line
    :type desc: str
    :param args: command line arguments usually :py:func:`sys.argv[1:]`
    :type args: list
    :return: arguments parsed by :py:mod:`argparse`
    :rtype: :py:class:`argparse.Namespace`
    """
    parser = argparse.ArgumentParser(description=desc,
                                     formatter_class=constants.ArgParseFormatter)
    parser.add_argument('outdir', help='Output directory')
    parser.add_argument('--embeddings', nargs='+',
                        help='Filepath to .tsv with embeddings. Requires two or more paths.')
    parser.add_argument('--embedding_names', nargs='+',
                        help='Name corresponding to each filepath input in --embeddings. ')
    parser.add_argument('--algorithm', choices=['auto', 'muse'], default='auto',
                        help='Algorithm to use for coembedding. Defaults to auto.')
    parser.add_argument(PPI_EMBEDDINGDIR,
                        help='Directory aka rocrate where ppi '
                             'embedding file resides (Deprecated: use --embeddings flag)')
    parser.add_argument(IMAGE_EMBEDDINGDIR,
                        help='Directory aka rocrate image embedding '
                             'file resides (Deprecated: use --embeddings flag)')
    parser.add_argument('--latent_dimension', type=int, default=128,
                        help='Output dimension of embedding')
    parser.add_argument('--n_epochs_init', default=200, type=int,
                        help='# of init training epochs')
    parser.add_argument('--n_epochs', default=500, type=int,
                        help='# of training epochs')
    parser.add_argument('--jackknife_percent', default=0.0, type=float,
                        help='Percentage of data to withhold from training'
                             'a value of 0.1 means to withhold 10 percent of the data')
    parser.add_argument('--fake_embedding', action='store_true',
                        help='If set, generate fake coembeddings')
    parser.add_argument('--name',
                        help='Name of this run, needed for FAIRSCAPE. If '
                             'unset, name value from specified '
                             'by --embeddings directories will be used')
    parser.add_argument('--organization_name',
                        help='Name of organization running this tool, needed '
                             'for FAIRSCAPE. If unset, organization name specified '
                             'in --embedding directories will be used')
    parser.add_argument('--project_name',
                        help='Name of project running this tool, needed for '
                             'FAIRSCAPE. If unset, project name specified '
                             'in --embedding directories will be used')
    parser.add_argument('--logconf', default=None,
                        help='Path to python logging configuration file in '
                             'this format: https://docs.python.org/3/library/'
                             'logging.config.html#logging-config-fileformat '
                             'Setting this overrides -v parameter which uses '
                             ' default logger. (default None)')
    parser.add_argument('--skip_logging', action='store_true',
                        help='If set, output.log, error.log '
                             'files will not be created')
    parser.add_argument('--verbose', '-v', action='count', default=1,
                        help='Increases verbosity of logger to standard '
                             'error for log messages in this module. Messages are '
                             'output at these python logging levels '
                             '-v = WARNING, -vv = INFO, '
                             '-vvv = DEBUG, -vvvv = NOTSET (default ERROR '
                             'logging)')
    parser.add_argument('--version', action='version',
                        version=('%(prog)s ' +
                                 cellmaps_coembedding.__version__))

    return parser.parse_args(args)


def main(args):
    """
    Main entry point for program

    :param args: arguments passed to command line usually :py:func:`sys.argv[1:]`
    :type args: list

    :return: return value of :py:meth:`cellmaps_coembedding.runner.CellmapsCoEmbedder.run`
             or ``2`` if an exception is raised
    :rtype: int
    """
    desc = """
    Version {version}

    Given input embeddings, this tool generates a co-embedding using either a UniEmbed algorith or
    a variant of MuSE algorithm within this code base from
    Feng Bao @ Altschuler & Wu Lab @ UCSF 2022
    that is under MIT License.

    To run this tool requires that an output directory be specified and two embeddings
    be set via --embeddings flag. The values passed to --embeddings can be an ro-crate
    containing either a ppi_emd.tsv or image_emd.tsv file or a path to a TSV file.

    It is assumed these files are tab delimited embeddings and for each row,
    first value is assumed to be sample ID followed by the embeddings separated by
    tabs. The first row is assumed to be a header.



    """.format(version=cellmaps_coembedding.__version__)
    theargs = _parse_arguments(desc, args[1:])
    theargs.program = args[0]
    theargs.version = cellmaps_coembedding.__version__

    if (theargs.ppi_embeddingdir or theargs.image_embeddingdir) and theargs.embeddings:
        raise CellmapsCoEmbeddingError('Use either --ppi_embeddingdir and --image_embeddingdir or --embeddings, '
                                       'not both')
    if theargs.embeddings:
        if len(theargs.embeddings) > 2 and theargs.algorithm == 'muse':
            raise CellmapsCoEmbeddingError('Only two embeddings are supported with --embeddings for MUSE algorithm')

    if not (theargs.ppi_embeddingdir and theargs.image_embeddingdir) and not theargs.embeddings:
        raise CellmapsCoEmbeddingError('Either --ppi_embeddingdir and --image_embeddingdir, '
                                       'or --embeddings are required')

    try:
        logutils.setup_cmd_logging(theargs)
        if theargs.fake_embedding:
            gen = FakeCoEmbeddingGenerator(dimensions=theargs.latent_dimension,
                                           ppi_embeddingdir=theargs.ppi_embeddingdir,
                                           image_embeddingdir=theargs.image_embeddingdir,
                                           embeddings=theargs.embeddings,
                                           embedding_names=theargs.embedding_names)
        else:
            if theargs.algorithm == 'muse':
                gen = MuseCoEmbeddingGenerator(dimensions=theargs.latent_dimension,
                                               ppi_embeddingdir=theargs.ppi_embeddingdir,
                                               image_embeddingdir=theargs.image_embeddingdir,
                                               n_epochs=theargs.n_epochs,
                                               n_epochs_init=theargs.n_epochs_init,
                                               jackknife_percent=theargs.jackknife_percent,
                                               outdir=os.path.abspath(theargs.outdir),
                                               embeddings=theargs.embeddings,
                                               embedding_names=theargs.embedding_names)
            if theargs.algorithm == 'auto':
                gen = AutoCoEmbeddingGenerator(dimensions=theargs.latent_dimension,
                               ppi_embeddingdir=theargs.ppi_embeddingdir,
                               image_embeddingdir=theargs.image_embeddingdir,
                               n_epochs=theargs.n_epochs,
                               jackknife_percent=theargs.jackknife_percent,
                               outdir=os.path.abspath(theargs.outdir),
                               embeddings=theargs.embeddings,
                               embedding_names=theargs.embedding_names)

        inputdirs = gen.get_embedding_inputdirs()
        return CellmapsCoEmbedder(outdir=theargs.outdir,
                                  inputdirs=inputdirs,
                                  embedding_generator=gen,
                                  name=theargs.name,
                                  organization_name=theargs.organization_name,
                                  project_name=theargs.project_name,
                                  skip_logging=theargs.skip_logging,
                                  input_data_dict=theargs.__dict__).run()
    except Exception as e:
        logger.exception('Caught exception: ' + str(e))
        return 2
    finally:
        logging.shutdown()


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main(sys.argv))
