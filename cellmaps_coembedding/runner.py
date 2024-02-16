#! /usr/bin/env python

import os
import csv
import random
import logging
import time
from datetime import date
import pandas as pd
import numpy as np
import dill
import sys
from tqdm import tqdm
from cellmaps_utils import constants
from cellmaps_utils import logutils
from cellmaps_utils.provenance import ProvenanceUtil
import cellmaps_coembedding
import cellmaps_coembedding.muse_sc as muse
from cellmaps_coembedding.exceptions import CellmapsCoEmbeddingError

logger = logging.getLogger(__name__)


class EmbeddingGenerator(object):
    """
    Base class for implementations that generate
    network embeddings
    """

    def __init__(self, dimensions=1024,
                 ppi_embeddingdir=None,
                 image_embeddingdir=None,
                 embedding_files=None,
                 embedding_names=None
                 ):
        """
        Constructor
        """
        self._dimensions = dimensions
        self._embedding_files, self._embedding_names = self._get_embedding_files_and_names(embedding_files, ppi_embeddingdir, image_embeddingdir, embedding_names)

    def _get_embedding_file_from_dirs(self, embedding_dir):
        path_ppi = os.path.join(embedding_dir,
                                constants.PPI_EMBEDDING_FILE)
        if os.path.exists(path_ppi):
            return path_ppi
        path_image = os.path.join(embedding_dir,
                                  constants.IMAGE_EMBEDDING_FILE)
        if os.path.exists(path_image):
            return path_image
        raise CellmapsCoEmbeddingError(f'Embedding file not found in {embedding_dir}')
        
   
    def _get_embedding_files_and_names(self, embedding_files, ppi_embeddingdir, image_embeddingdir, embedding_names):
        
        embeddings = []
        names = []

        if (ppi_embeddingdir or image_embeddingdir):
            if  embedding_files:
                raise CellmapsCoEmbeddingError('Use either ppi_embeddingdir and image_embeddingdir or embeddings, '
                                               'not both')
            ppi_embedding_file = self._get_embedding_file_from_dirs(ppi_embeddingdir)
            image_embedding_file = self._get_embedding_file_from_dirs(image_embeddingdir)
            embeddings = [ppi_embedding_file, image_embedding_file]
            if embedding_names is None:
                names = ['PPI', 'image']
        else:
            embeddings = embedding_files
            names = embedding_names
            
        if names is None:
            names = ['emd_{}'.format(x) for x in np.arange(len(embedding_files))]
        if len(names) != len(embeddings):
            raise CellmapsCoEmbeddingError('Input list of embedding names does not match number of embeddings.')
        
        return embeddings, names
         
    def get_embedding_files(self):
        return self._embedding_files   
             
    
    def _get_set_of_gene_names(self, embedding):
        """
        Get a set of gene names from **embedding**

        :param embedding:
        :return:
        """
        name_set = set()
        for entry in embedding:
            name_set.add(entry[0])
        return name_set

    def _get_embeddings(self, embedding_file):
        """
        Gets embedding as a list or lists

        :param embedding_file: Path to embedding file
        :type embedding_file: str
        :return: embeddings
        :rtype: list
        """
        embeddings = []
        with open(embedding_file, 'r') as f:
            reader = csv.reader(f, delimiter='\t')
            next(reader, None)
            for row in reader:
                embeddings.append(row)
        return embeddings

    def get_dimensions(self):
        """
        Gets number of dimensions this embedding will generate

        :return: number of dimensions aka vector length
        :rtype: int
        """
        return self._dimensions

    def get_next_embedding(self):
        """
        Generator method for getting next embedding.
        Caller should implement with ``yield`` operator

        :raises: NotImplementedError: Subclasses should implement this
        :return: Embedding
        :rtype: list
        """
        raise NotImplementedError('Subclasses should implement')


class MuseCoEmbeddingGenerator(EmbeddingGenerator):
    """
    Generats co-embedding using MUSE
    """

    def __init__(self, dimensions=128,
                 k=10, triplet_margin=0.1, dropout=0.25, n_epochs=500,
                 n_epochs_init=200,
                 outdir=None,
                 embedding_files=None,
                 ppi_embeddingdir=None,
                 image_embeddingdir=None,
                 embedding_names=None,
                 jackknife_percent=0,
                 ):
        """

        :param dimensions:
        :param k: k nearest neighbors value used for clustering - clustering used for triplet loss
        :param triplet_margin: margin for triplet loss
        :param dropout: dropout between neural net layers
        :param n_epochs: training epochs
        :param n_epochs_init: initialization training epochs
        :param outdir:
        :param ppi_embeddingdir:
        :param image_embeddingdir:
        :param jackknife_percent: percent of data to withhold from training
        """
        super().__init__(dimensions=dimensions, embedding_files=embedding_files,
                         ppi_embeddingdir=ppi_embeddingdir,
                         image_embeddingdir=image_embeddingdir,
                         embedding_names=embedding_names
                         )
        self._outdir = outdir
        self._k = k
        self.triplet_margin = triplet_margin
        self._dropout = dropout
        self._n_epochs = n_epochs
        self._n_epochs_init = n_epochs_init
        self._jackknife_percent = jackknife_percent

    def get_next_embedding(self):
        """

        :return:
        """
        embeddings = [self._get_embeddings(x) for x in self._embedding_files]
        for index in np.arange(len(embeddings)):
            e = embeddings[index]
            e.sort(key=lambda x: x[0])
            logger.info('There are ' + str(len(e)) + ' ' + self._embedding_names[index] + ' embeddings')
        
        embedding_name_sets = [self._get_set_of_gene_names(x) for x in embeddings]
        intersection_name_set = embedding_name_sets[0].intersection(embedding_name_sets[1])
       
        logger.info('There are ' +
                    str(len(intersection_name_set)) +
                    ' overlapping embeddings')

        name_index = [x[0] for x in embeddings[0] if x[0] in intersection_name_set]

        embedding_data = []
        for e in embeddings:
            embedding_data.append(np.array([np.array([float(v) for v in xi[1:]]) for xi in e if xi[0] in intersection_name_set]))
        
        resultsdir = os.path.join(self._outdir, 'muse')

        test_subset = random.sample(list(np.arange(len(name_index))), int(self._jackknife_percent * len(name_index)))
        if self._jackknife_percent > 0:
            with open('{}_test_genes.txt'.format(resultsdir), 'w') as file:
                file.write('\n'.join(np.array(name_index)[test_subset]))

        embedding_names = self._embedding_names
               
        model, res_embedings = muse.muse_fit_predict(resultsdir=resultsdir,
                                                     modality_data=embedding_data,
                                                     modality_names=embedding_names,
                                                     name_index=name_index,
                                                     test_subset=test_subset,
                                                     latent_dim=self.get_dimensions(),
                                                     n_epochs=self._n_epochs,
                                                     n_epochs_init=self._n_epochs_init,
                                                     triplet_margin=self.triplet_margin,
                                                     k=self._k, dropout=self._dropout)
        for index, embedding in enumerate(res_embedings):
            row = [name_index[index]]
            row.extend(embedding)
            yield row

                        
class FakeCoEmbeddingGenerator(EmbeddingGenerator):
    """
    Generates a fake coembedding for intersection of embedding dirs
    """

    def __init__(self, dimensions=128, ppi_embeddingdir=None,
                 image_embeddingdir=None, embedding_files=None, embedding_names=None):
        """
        Constructor
        :param dimensions:
        """
        super().__init__(dimensions=dimensions,
                         ppi_embeddingdir=ppi_embeddingdir,
                         image_embeddingdir=image_embeddingdir,
                         embedding_files=embedding_files,
                        embedding_names=embedding_names)

    def get_next_embedding(self):
        """
        Gets next embedding

        :return:
        """
        modality_embeddings = [self._get_embeddings(x) in self._embedding_files]
        for index in np.arange(len(modality_embeddings)):
            embeddings = modality_embeddings[index]
            embeddings.sort(key=lambda x: x[0])
            logger.info('There are ' + str(len(embeddings)) + ' ' + self._embedding_names[index] + ' embeddings')
            
        modality_name_sets = [self._get_set_of_embedding_names(x) for x in modality_embeddings]
        intersection_name_set = modality_name_sets[0].intersection(modality_name_sets[1])
       
        logger.info('There are ' +
                    str(len(intersection_name_set)) +
                    ' overlapping embeddings')
        
        for embed_name in intersection_name_set:
            row = [embed_name]
            row.extend([random.random() for x in range(0, self.get_dimensions())])
            yield row


class CellmapsCoEmbedder(object):
    """
    Class to run algorithm
    """

    def __init__(self, outdir=None,
                 embedding_generator=None,
                 name=None,
                 organization_name=None,
                 project_name=None,
                 provenance_utils=ProvenanceUtil(),
                 skip_logging=True,
                 input_data_dict=None):
        """
        Constructor
        :param outdir: Directory to write the results of this tool
        :type outdir: str
        :param inputdir: Output directory where embeddings to be coembedded are located
                         (output of cellmaps_image_embedding and cellmaps_ppi_embedding)
        :type inputdir: str
        :param embedding_generator:
        :param skip_logging: If ``True`` skip logging, if ``None`` or ``False`` do NOT skip logging
        :type skip_logging: bool
        :param name:
        :type name: str
        :param organization_name:
        :type organization_name: str
        :param project_name:
        :type project_name: str
        :param input_data_dict:
        :type input_data_dict: dict
        """
        if outdir is None:
            raise CellmapsCoEmbeddingError('outdir is None')
        self._outdir = os.path.abspath(outdir)
        self._start_time = int(time.time())
        self._end_time = -1
        self._name = name
        self._project_name = project_name
        self._organization_name = organization_name
        self._provenance_utils = provenance_utils
        self._keywords = None
        self._description = None
        self._embedding_generator = embedding_generator
        self._inputdirs = self._get_embedding_dirs(self._embedding_generator.get_embedding_files()) 
        self._input_data_dict = input_data_dict
        self._softwareid = None
        self._coembedding_id = None
        self._inputdir_is_rocrate = None

        if skip_logging is None:
            self._skip_logging = False
        else:
            self._skip_logging = skip_logging

        logger.debug('In constructor')

    def _get_embedding_dirs(self, embeddings):
        dirs = []
        for embed in embeddings:
            if os.path.isfile(embed):
                dirs.append(os.path.dirname(embed))
            else:
                dirs.append(embed)

        return dirs
    
    
    def _update_provenance_fields(self):
        """

        :return:
        """
        rocrate_dirs = []
        if self._inputdirs is not None:
            for embeddind_dir in self._inputdirs:
                if os.path.exists(os.path.join(embeddind_dir, constants.RO_CRATE_METADATA_FILE)):
                    rocrate_dirs.append(embeddind_dir)
        if len(rocrate_dirs) > 0:
            prov_attrs = self._provenance_utils.get_merged_rocrate_provenance_attrs(rocrate_dirs,
                                                                                    override_name=self._name,
                                                                                    override_project_name=
                                                                                    self._project_name,
                                                                                    override_organization_name=
                                                                                    self._organization_name,
                                                                                    extra_keywords=['merged embedding'])

            self._name = prov_attrs.get_name()
            self._organization_name = prov_attrs.get_organization_name()
            self._project_name = prov_attrs.get_project_name()
            self._keywords = prov_attrs.get_keywords()
            self._description = prov_attrs.get_description()
        else:
            self._name = 'Coembedding tool'
            self._organization_name = 'Example'
            self._project_name = 'Example'
            self._keywords = ['coembedding']
            self._description = 'Example input dataset Coembedding'

    def _write_task_start_json(self):
        """
        Writes task_start.json file with information about
        what is to be run

        """
        data = {}

        if self._input_data_dict is not None:
            data['commandlineargs'] = self._input_data_dict

        logutils.write_task_start_json(outdir=self._outdir,
                                       start_time=self._start_time,
                                       version=cellmaps_coembedding.__version__,
                                       data=data)

    def _create_rocrate(self):
        """
        Creates rocrate for output directory

        :raises CellMapsProvenanceError: If there is an error
        """
        try:
            self._provenance_utils.register_rocrate(self._outdir,
                                                    name=self._name,
                                                    organization_name=self._organization_name,
                                                    project_name=self._project_name,
                                                    description=self._description,
                                                    keywords=self._keywords)
        except TypeError as te:
            raise CellmapsCoEmbeddingError('Invalid provenance: ' + str(te))
        except KeyError as ke:
            raise CellmapsCoEmbeddingError('Key missing in provenance: ' + str(ke))

    def _register_software(self):
        """
        Registers this tool

        :raises CellMapsImageEmbeddingError: If fairscape call fails
        """
        software_keywords = self._keywords
        software_keywords.extend(['tools', cellmaps_coembedding.__name__])
        software_description = self._description + ' ' + \
                               cellmaps_coembedding.__description__
        self._softwareid = self._provenance_utils.register_software(self._outdir,
                                                                    name=cellmaps_coembedding.__name__,
                                                                    description=software_description,
                                                                    author=cellmaps_coembedding.__author__,
                                                                    version=cellmaps_coembedding.__version__,
                                                                    file_format='py',
                                                                    keywords=software_keywords,
                                                                    url=cellmaps_coembedding.__repo_url__)

    def _register_computation(self):
        """
        # Todo: added inused dataset, software and what is being generated
        :return:
        """
        logger.debug('Getting id of input rocrate')
        used_dataset = []
        for entry in self._inputdirs:
            if os.path.exists(os.path.join(entry, constants.RO_CRATE_METADATA_FILE)):
                used_dataset.append(self._provenance_utils.get_id_of_rocrate(entry))

        keywords = self._keywords
        keywords.extend(['computation'])
        description = self._description + ' run of ' + cellmaps_coembedding.__name__

        self._provenance_utils.register_computation(self._outdir,
                                                    name=cellmaps_coembedding.__computation_name__,
                                                    run_by=str(self._provenance_utils.get_login()),
                                                    command=str(self._input_data_dict),
                                                    description=description,
                                                    keywords=keywords,
                                                    used_software=[self._softwareid],
                                                    used_dataset=used_dataset,
                                                    generated=[self._coembedding_id])

    def _register_image_coembedding_file(self):
        """
        Registers coembedding file with create as a dataset

        """
        description = self._description
        description += ' Co-Embedding file'
        keywords = self._keywords
        keywords.extend(['file'])
        data_dict = {'name': os.path.basename(self.get_coembedding_file()) + ' coembedding output file',
                     'description': description,
                     'keywords': keywords,
                     'data-format': 'tsv',
                     'author': cellmaps_coembedding.__name__,
                     'version': cellmaps_coembedding.__version__,
                     'date-published': date.today().strftime(self._provenance_utils.get_default_date_format_str())}
        self._coembedding_id = self._provenance_utils.register_dataset(self._outdir,
                                                                       source_file=self.get_coembedding_file(),
                                                                       data_dict=data_dict,
                                                                       skip_copy=True)

    def get_coembedding_file(self):
        """
        Gets image embedding file
        :return:
        """
        return os.path.join(self._outdir, constants.CO_EMBEDDING_FILE)

    def run(self):
        """
        Runs CM4AI Generate COEMBEDDINGS


        :return:
        """
        logger.debug('In run method')
        exitcode = 99
        try:
            if self._outdir is None:
                raise CellmapsCoEmbeddingError('outdir must be set')

            if not os.path.isdir(self._outdir):
                os.makedirs(self._outdir, mode=0o755)

            if self._skip_logging is False:
                logutils.setup_filelogger(outdir=self._outdir,
                                          handlerprefix='cellmaps_coembedding')
            self._write_task_start_json()
            if self._inputdirs is None:
                raise CellmapsCoEmbeddingError('No embeddings provided')

            self._update_provenance_fields()
            self._create_rocrate()
            self._register_software()

            # generate result
            with open(os.path.join(self._outdir, constants.CO_EMBEDDING_FILE), 'w', newline='') as f:
                writer = csv.writer(f, delimiter='\t')
                header_line = ['']
                header_line.extend([x for x in range(1, self._embedding_generator.get_dimensions())])
                writer.writerow(header_line)
                for row in tqdm(self._embedding_generator.get_next_embedding(), desc='Saving embedding'):
                    writer.writerow(row)

            self._register_image_coembedding_file()

            self._register_computation()

            exitcode = 0
        finally:
            self._end_time = int(time.time())
            # write a task finish file
            logutils.write_task_finish_json(outdir=self._outdir,
                                            start_time=self._start_time,
                                            end_time=self._end_time,
                                            status=exitcode)
        logger.debug('Exit code: ' + str(exitcode))
        return exitcode
