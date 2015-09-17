# -*- coding: utf-8 -*-

from sqlalchemy.orm import sessionmaker, aliased
from sqlalchemy import desc, func, or_
import pytest
import sys
from cobra.io import read_sbml_model, load_matlab_model, load_json_model
import pytest
import numpy
from os.path import abspath, dirname, join, exists
from os import listdir
from numpy.testing import assert_almost_equal
from decimal import Decimal
import cPickle as pickle
import re
from time import time

from ome.models import *
from ome.base import Session
from ome import settings
from ome.dumping.model_dumping import dump_model
from ome.loading.parse import convert_ids

from bigg2.server import (directory as bigg_root_directory,
                          static_model_dir)


# Make a list of models to test

DEBUG = True
if DEBUG:
    model_files = ['iECOK1_1307.xml']
else:
    model_files = [x for x in listdir(settings.model_directory)
                   if x.endswith('.xml') or x.endswith('.mat')]


# make the fixtures

@pytest.fixture(scope='session')
def session(request):
    """Make a session"""
    def teardown():
        Session.close_all()
    request.addfinalizer(teardown)

    return Session()


@pytest.fixture(scope='session', params=model_files)
def pub_model(request):
    # get a specific model. This fixture and all the tests that use it will run
    # for every model in the model_files list.
    model_file = request.param
    model_path = join(settings.model_directory, model_file)

    # load the file
    start = time()
    try:
        if model_path.endswith('.xml'):
            pub_model = read_sbml_model(model_path)
        elif model_path.endswith('.mat'):
            pub_model = load_matlab_model(model_path)
        else:
            raise Exception('Unrecongnized extension for model %s' % model_file)
    except IOError:
        raise Exception('Could not find model %s' % model_path)
    print("Loaded %s in %.2f sec" % (model_file, time() - start))

    return pub_model


@pytest.fixture(scope='session')
def db_model(pub_model):
    # dump the model
    start = time()
    db_model = dump_model(pub_model.id)
    print("Dumped %s in %.2f sec" % (pub_model.id, time() - start))
    return db_model


# model tests will run for every model in the model_files list

def test_reaction_count(db_model, pub_model):
    assert len(db_model.reactions) == len(pub_model.reactions)

    # count elements. be sure to removed duplicates from the published model
    # assert len(db_model.reactions) == len(set([x.id for x in pub_model.reactions]))


def test_metabolite_count(db_model, pub_model):
    assert len(db_model.reactions) == len(pub_model.reactions)

    # TODO for these two models, check the metabolites cer2_24_c and
    # cer2__24_c, cer2_24_c and cer2'_24_c
    # if model.id != 'iMM904' and model.id != 'iND750':
    #     dat_metabolites_len = len(model.metabolites)
    #     pub_metabolites_len = len(set([x.id for x in published_model.metabolites]))
    #     if dat_metabolites_len != pub_metabolites_len:
    #         errors.append(['{} metabolites counts do not match: database {} published {}'
    #                     .format(model_path, dat_metabolites_len, pub_metabolites_len),
    #                     compare_sets(model.metabolites, published_model.metabolites, ignore_boundary=True)])


def test_gene_count(db_model, pub_model):
    # also check for merged genes
    pub_genes_len = len(pub_model.genes)
    db_genes_len = len(db_model.genes)

    # find merged genes
    db_merged = [(g.id, g.notes['original_bigg_ids']) for g in db_model.genes]
    for bigg_id, originals in db_merged:
        if len(originals) <= 0:
            raise Exception('Missing original gene id for {} in {}'
                            .format(bigg_id, db_model.id))

    db_merged_extra = sum([len(x[1]) - 1 for x in db_merged])
    if db_merged_extra > 0:
        print('{} genes merged in model {}: {}'
              .format(db_merged_extra, db_model.id, {x[0]: x[1] for x in db_merged if len(x[1]) > 1}))
    assert db_genes_len + db_merged_extra == pub_genes_len


id_reg = re.compile(r'[~a-zA-Z0-9_]')

def test_reaction_ids(db_model):
    assert [x.id for x in db_model.reactions if id_reg.find(x.id)] == []






def _compare_sets(dictlist1, dictlist2, ignore_boundary=False):
    """Find the difference between the reaction, metabolite, or gene sets."""
    sets = [set([x.id for x in dl if (not ignore_boundary or not x.id.endswith('_b'))])
            for dl in [dictlist1, dictlist2]]
    return list(set.symmetric_difference(*sets))


def test_compartment_names(session):
    assert (session
            .query(Compartment.name)
            .filter(Compartment.bigg_id == 'c')
            .first())[0] == 'cytosol'


def test_sbml_input_output(session):

    # loaded published models
    published_models = {}
    with open(settings.model_genome, 'r') as f:
        for line in f.readlines():
            model_file = join(settings.data_directory, 'models', line.split('\t')[0])
            try:
                print('Loading %s' % model_file)
                if model_file.endswith('.xml'):
                    model = read_sbml_model(model_file)
                elif model_file.endswith('.mat'):
                    model = load_matlab_model(model_file)
                else:
                    print('Bad model file {}'.format(model_file))
            except IOError:
                print('Could not find model file %s' % model_file)
                continue

            # Convert the ids for comparison. This also removes _b
            # metabolites which prevent solving in COBRApy.
            published_models[model.id], _ = convert_ids(model)

    errors = []
    model_paths = []
    # get files to test
    for model_file in listdir(static_model_dir):
        if model_file.endswith('.json'):
            model_id = model_file[:-5]
        elif model_file.endswith('.xml'):
            model_id = model_file[:-4]
        elif model_file.endswith('.mat'):
            model_id = model_file[:-4]
        else:
            continue
        if model_id in published_models.keys():
            model_paths.append(join(static_model_dir, model_file))

    # test each model
    print 'testing {} models'.format(len(model_paths))
    error_len = len(errors)
    for model_path in model_paths:
        if len(errors) > error_len:
            import ipdb; ipdb.set_trace()
            error_len += 1

        print('Testing {}'.format(model_path))

        if model_path.endswith('.xml'):
            try:
                model = read_sbml_model(model_path)
            except Exception as e:
                errors.append('{}: {}'.format(model_path, e.message))
                continue
        elif model_path.endswith('.json'):
            try:
                model = load_json_model(model_path)
            except Exception as e:
                errors.append('{}: {}'.format(model_path, e.message))
                continue
        elif model_path.endswith('.mat'):
            try:
                model = load_matlab_model(model_path)
            except Exception as e:
                errors.append('{}: {}'.format(model_path, e.message))
                continue
        else:
            errors.append('Bad model file {}'.format(model_path))
            continue

        try:
            published_model = published_models[model.id]
        except KeyError:
            errors.append('Could not find published model for database model %s' % model.id)
            continue

        solution1 = model.optimize()
        solution2 = published_model.optimize()
        f1 = 0.0 if solution1.f is None else solution1.f
        f2 = 0.0 if solution2.f is None else solution2.f
        diff = abs(f1 - f2)
        if diff >= 1e-5:
            try:
                errors.append('{} solutions do not match: database {:.5f} published {:.5f}'
                            .format(model_path, f1, f2))
            except ValueError:
                print 'fix', model_path, f1, f2

        # test mass balance
        for r in model.reactions:
            if (re.match(r'EX_.*', r.id) or re.match(r'DM_.*', r.id)
                or re.match(r'sink_.*', r.id, re.IGNORECASE)
                or re.match(r'.*biomass.*', r.id, re.IGNORECASE)):
                continue
            mass_balance = r.check_mass_balance()
            if len(mass_balance) != 0:
                try:
                    published_reaction = published_model.reactions.get_by_id(r.id)
                except KeyError:
                    errors.append('{}: Bad mass balance in {}: {}. Not found in published model.'
                                  .format(model_path, r.id, mass_balance))
                else:
                    p_mass_balance = published_reaction.check_mass_balance()
                    if len(p_mass_balance) == 0:
                        errors.append('{}: Bad mass balance in {}: {}. Reaction is balanced in published model.'
                                      .format(model_path, r.id, mass_balance))
                    else:
                        errors.append('{}: Bad mass balance in {} ({}) and in published model ({}).'
                                      .format(model_path, r.id, mass_balance, p_mass_balance))

    assert len(errors) == 0


def test_dad_2(session):
    """Tests for a bug that occurs with dad__2_c vs. dad_2_c. Fails if you load
    iAF1260 then iMM904.

    In [44]: session.query(Component.bigg_id, Compartment.bigg_id, Model.bigg_id, Reaction.bigg_id).join(CompartmentalizedComponent, CompartmentalizedComponent.component_id==Component.id).join(Compartment, Compartment.id==CompartmentalizedComponent.compartment_id).join(ReactionMatrix, ReactionMatrix.compartmentalized_component_id==CompartmentalizedComponent.id).join(Reaction).join(ModelReaction).join(Model).filter(Model.bigg_id=='iAF1260').filter(Reaction.bigg_id.like('DADA')).all()

    Out[44]:
    [(u'dad__2', u'c', u'iAF1260', u'DADA'),
    (u'din', u'c', u'iAF1260', u'DADA'),
    (u'h2o', u'c', u'iAF1260', u'DADA'),
    (u'h', u'c', u'iAF1260', u'DADA'),
    (u'nh4', u'c', u'iAF1260', u'DADA'),
    (u'dad_2', u'c', u'iAF1260', u'DADA')]

    """
    res_db = (session
              .query(Component.bigg_id, Compartment.bigg_id, Model.bigg_id, Reaction.bigg_id)
              .join(CompartmentalizedComponent, CompartmentalizedComponent.component_id==Component.id)
              .join(Compartment, Compartment.id==CompartmentalizedComponent.compartment_id)
              .join(ReactionMatrix, ReactionMatrix.compartmentalized_component_id==CompartmentalizedComponent.id)
              .join(Reaction)
              .join(ModelReaction)
              .join(Model)
              .filter(Model.bigg_id=='iAF1260')
              .filter(Reaction.bigg_id == 'DADA')
              .filter(Component.bigg_id.like('dad_%2'))
              .all())
    assert len(res_db) == 1
    session.close()


def test_reaction_matrix(session):
    matrix = (session
              .query(Reaction.bigg_id, ReactionMatrix.stoichiometry, Metabolite)
              .join(ReactionMatrix, ReactionMatrix.reaction_id == Reaction.id)
              .filter(Reaction.bigg_id == 'GLCtex')
              .join(CompartmentalizedComponent)
              .join(Metabolite)
              .all())
    assert Decimal(1.0) in [x[1] for x in matrix]
    assert Decimal(-1.0) in [x[1] for x in matrix]


def test_models_for_bigg_style_ids(session):
    """Make sure all models use BiGG style IDs by checking for 'pyr'."""
    has_pyr = {}
    for model in session.query(Model).all():
        mcc = (session
               .query(ModelCompartmentalizedComponent)
               .join(Model,
                     Model.id == ModelCompartmentalizedComponent.model_id)
               .join(CompartmentalizedComponent,
                     CompartmentalizedComponent.id == ModelCompartmentalizedComponent.compartmentalized_component_id)
               .join(Component,
                     Component.id == CompartmentalizedComponent.component_id)
               .filter(Model.id == model.id)
               .filter(Component.bigg_id =="pyr")
               .first())
        has_pyr[model.bigg_id] = (mcc is not None)
    print 'No pyr: %s' % ', '.join([k for k, v in has_pyr.iteritems() if not v])
    assert all(has_pyr.values())


def test_formulas_for_metabolites(session):
    """Make sure all metabolites have formulas."""
    # check for components with no formula
    res = session.query(Metabolite).all()
    metabolites_without_formula = {x.bigg_id: x.formula for x in res
                                   if x.formula is None or x.formula.strip() == ''}
    # succoa should definitely have a formula
    assert 'succoa' not in metabolites_without_formula.keys()
    # this number will not be zero
    assert len(metabolites_without_formula) < 647


def test_leading_underscores(session):
    """Make sure metabolites and reactions do not have leading underscores."""
    res = (session
           .query(Metabolite)
           .filter(Metabolite.bigg_id.like('\_%'))
           .all())
    assert len(res) == 0
    res = (session
           .query(Reaction)
           .filter(Reaction.bigg_id.like('\_%'))
           .all())
    assert len(res) == 0


def test_model_directories():
    assert exists(join(bigg_root_directory, 'static', 'models', 'iJO1366.xml'))
    assert exists(join(bigg_root_directory, 'static', 'models', 'raw', 'iJO1366.xml'))
    assert exists(join(bigg_root_directory, 'static', 'models', 'iJO1366.mat'))
    assert exists(join(bigg_root_directory, 'static', 'models', 'iJO1366.json'))


if __name__ == "__main__":
    if len(sys.argv) == 4:
        if str(sys.argv[1]) == 'models':
            model1 = str(sys.argv[2])
            model2 = str(sys.argv[3])
            #print "the reations that are shared between these two models are:"
            sharedReactions(model1, model2)
            #print "the metabolites that are shared between these two models are:"
            shardMetabolites(model1, model2)
