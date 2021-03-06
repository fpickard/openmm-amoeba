import unittest
from validateConstraints import *
from simtk.openmm.app import *
from simtk.openmm import *
from simtk.unit import *
import simtk.openmm.app.element as elem
import simtk.openmm.app.forcefield as forcefield
import math
try:
    from cStringIO import StringIO
except ImportError:
    from io import StringIO
import os

class TestForceField(unittest.TestCase):
    """Test the ForceField.createSystem() method."""

    def setUp(self):
        """Set up the tests by loading the input pdb files and force field
        xml files.

        """
        # alanine dipeptide with explicit water
        self.pdb1 = PDBFile('systems/alanine-dipeptide-explicit.pdb')
        self.forcefield1 = ForceField('amber99sb.xml', 'tip3p.xml')
        self.topology1 = self.pdb1.topology
        self.topology1.setUnitCellDimensions(Vec3(2, 2, 2))

        # alanine dipeptide with implicit water
        self.pdb2 = PDBFile('systems/alanine-dipeptide-implicit.pdb')
        self.forcefield2 = ForceField('amber99sb.xml', 'amber99_obc.xml')


    def test_NonbondedMethod(self):
        """Test all five options for the nonbondedMethod parameter."""

        methodMap = {NoCutoff:NonbondedForce.NoCutoff,
                     CutoffNonPeriodic:NonbondedForce.CutoffNonPeriodic,
                     CutoffPeriodic:NonbondedForce.CutoffPeriodic,
                     Ewald:NonbondedForce.Ewald, PME: NonbondedForce.PME}
        for method in methodMap:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                  nonbondedMethod=method)
            forces = system.getForces()
            self.assertTrue(any(isinstance(f, NonbondedForce) and
                                f.getNonbondedMethod()==methodMap[method]
                                for f in forces))

    def test_DispersionCorrection(self):
        """Test to make sure the nonbondedCutoff parameter is passed correctly."""

        for useDispersionCorrection in [True, False]:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                   nonbondedCutoff=2*nanometer,
                                                   useDispersionCorrection=useDispersionCorrection)

            for force in system.getForces():
                if isinstance(force, NonbondedForce):
                    self.assertEqual(useDispersionCorrection, force.getUseDispersionCorrection())

    def test_Cutoff(self):
        """Test to make sure the nonbondedCutoff parameter is passed correctly."""

        for method in [CutoffNonPeriodic, CutoffPeriodic, Ewald, PME]:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                   nonbondedMethod=method,
                                                   nonbondedCutoff=2*nanometer,
                                                   constraints=HBonds)
            cutoff_distance = 0.0*nanometer
            cutoff_check = 2.0*nanometer
            for force in system.getForces():
                if isinstance(force, NonbondedForce):
                    cutoff_distance = force.getCutoffDistance()
            self.assertEqual(cutoff_distance, cutoff_check)

    def test_RemoveCMMotion(self):
        """Test both options (True and False) for the removeCMMotion parameter."""
        for b in [True, False]:
            system = self.forcefield1.createSystem(self.pdb1.topology,removeCMMotion=b)
            forces = system.getForces()
            self.assertEqual(any(isinstance(f, CMMotionRemover) for f in forces), b)

    def test_RigidWaterAndConstraints(self):
        """Test all eight options for the constraints and rigidWater parameters."""

        topology = self.pdb1.topology
        for constraints_value in [None, HBonds, AllBonds, HAngles]:
            for rigidWater_value in [True, False]:
                system = self.forcefield1.createSystem(topology,
                                                       constraints=constraints_value,
                                                       rigidWater=rigidWater_value)
                validateConstraints(self, topology, system,
                                    constraints_value, rigidWater_value)

    def test_ImplicitSolvent(self):
        """Test the four types of implicit solvents using the implicitSolvent
        parameter.

        """

        topology = self.pdb2.topology
        system = self.forcefield2.createSystem(topology)
        forces = system.getForces()
        self.assertTrue(any(isinstance(f, GBSAOBCForce) for f in forces))

    def test_ImplicitSolventParameters(self):
        """Test that solventDielectric and soluteDielectric are passed correctly
        for the different types of implicit solvent.

        """

        topology = self.pdb2.topology
        system = self.forcefield2.createSystem(topology, solventDielectric=50.0,
                                               soluteDielectric=0.9)
        found_matching_solvent_dielectric=False
        found_matching_solute_dielectric=False
        for force in system.getForces():
            if isinstance(force, GBSAOBCForce):
                if force.getSolventDielectric() == 50.0:
                    found_matching_solvent_dielectric = True
                if force.getSoluteDielectric() == 0.9:
                    found_matching_solute_dielectric = True
            if isinstance(force, NonbondedForce):
                self.assertEqual(force.getReactionFieldDielectric(), 1.0)
        self.assertTrue(found_matching_solvent_dielectric and
                        found_matching_solute_dielectric)

    def test_HydrogenMass(self):
        """Test that altering the mass of hydrogens works correctly."""

        topology = self.pdb1.topology
        hydrogenMass = 4*amu
        system1 = self.forcefield1.createSystem(topology)
        system2 = self.forcefield1.createSystem(topology, hydrogenMass=hydrogenMass)
        for atom in topology.atoms():
            if atom.element == elem.hydrogen:
                self.assertNotEqual(hydrogenMass, system1.getParticleMass(atom.index))
                self.assertEqual(hydrogenMass, system2.getParticleMass(atom.index))
        totalMass1 = sum([system1.getParticleMass(i) for i in range(system1.getNumParticles())]).value_in_unit(amu)
        totalMass2 = sum([system2.getParticleMass(i) for i in range(system2.getNumParticles())]).value_in_unit(amu)
        self.assertAlmostEqual(totalMass1, totalMass2)

    def test_Forces(self):
        """Compute forces and compare them to ones generated with a previous version of OpenMM to ensure they haven't changed."""

        pdb = PDBFile('systems/lysozyme-implicit.pdb')
        system = self.forcefield2.createSystem(pdb.topology)
        integrator = VerletIntegrator(0.001)
        context = Context(system, integrator)
        context.setPositions(pdb.positions)
        state1 = context.getState(getForces=True)
        with open('systems/lysozyme-implicit-forces.xml') as input:
            state2 = XmlSerializer.deserialize(input.read())
        numDifferences = 0
        for f1, f2, in zip(state1.getForces().value_in_unit(kilojoules_per_mole/nanometer), state2.getForces().value_in_unit(kilojoules_per_mole/nanometer)):
            diff = norm(f1-f2)
            if diff > 0.1 and diff/norm(f1) > 1e-3:
                numDifferences += 1
        self.assertTrue(numDifferences < system.getNumParticles()/20) # Tolerate occasional differences from numerical error

    def test_ProgrammaticForceField(self):
        """Test building a ForceField programmatically."""

        # Build the ForceField for TIP3P programmatically.
        ff = ForceField()
        ff.registerAtomType({'name':'tip3p-O', 'class':'OW', 'mass':15.99943*daltons, 'element':elem.oxygen})
        ff.registerAtomType({'name':'tip3p-H', 'class':'HW', 'mass':1.007947*daltons, 'element':elem.hydrogen})
        residue = ForceField._TemplateData('HOH')
        residue.atoms.append(ForceField._TemplateAtomData('O', 'tip3p-O', elem.oxygen))
        residue.atoms.append(ForceField._TemplateAtomData('H1', 'tip3p-H', elem.hydrogen))
        residue.atoms.append(ForceField._TemplateAtomData('H2', 'tip3p-H', elem.hydrogen))
        residue.addBond(0, 1)
        residue.addBond(0, 2)
        ff.registerResidueTemplate(residue)
        bonds = forcefield.HarmonicBondGenerator(ff)
        bonds.registerBond({'class1':'OW', 'class2':'HW', 'length':0.09572*nanometers, 'k':462750.4*kilojoules_per_mole/nanometer})
        ff.registerGenerator(bonds)
        angles = forcefield.HarmonicAngleGenerator(ff)
        angles.registerAngle({'class1':'HW', 'class2':'OW', 'class3':'HW', 'angle':1.82421813418*radians, 'k':836.8*kilojoules_per_mole/radian})
        ff.registerGenerator(angles)
        nonbonded = forcefield.NonbondedGenerator(ff, 0.833333, 0.5)
        nonbonded.registerAtom({'type':'tip3p-O', 'charge':-0.834, 'sigma':0.31507524065751241*nanometers, 'epsilon':0.635968*kilojoules_per_mole})
        nonbonded.registerAtom({'type':'tip3p-H', 'charge':0.417, 'sigma':1*nanometers, 'epsilon':0*kilojoules_per_mole})
        ff.registerGenerator(nonbonded)

        # Build a water box.
        modeller = Modeller(Topology(), [])
        modeller.addSolvent(ff, boxSize=Vec3(3, 3, 3)*nanometers)

        # Create a system using the programmatic force field as well as one from an XML file.
        system1 = ff.createSystem(modeller.topology)
        ff2 = ForceField('tip3p.xml')
        system2 = ff2.createSystem(modeller.topology)
        self.assertEqual(XmlSerializer.serialize(system1), XmlSerializer.serialize(system2))

    def test_PeriodicBoxVectors(self):
        """Test setting the periodic box vectors."""

        vectors = (Vec3(5, 0, 0), Vec3(-1.5, 4.5, 0), Vec3(0.4, 0.8, 7.5))*nanometers
        self.pdb1.topology.setPeriodicBoxVectors(vectors)
        self.assertEqual(Vec3(5, 4.5, 7.5)*nanometers, self.pdb1.topology.getUnitCellDimensions())
        system = self.forcefield1.createSystem(self.pdb1.topology)
        for i in range(3):
            self.assertEqual(vectors[i], self.pdb1.topology.getPeriodicBoxVectors()[i])
            self.assertEqual(vectors[i], system.getDefaultPeriodicBoxVectors()[i])

    def test_ResidueAttributes(self):
        """Test a ForceField that gets per-particle parameters from residue attributes."""

        xml = """
<ForceField>
 <AtomTypes>
  <Type name="tip3p-O" class="OW" element="O" mass="15.99943"/>
  <Type name="tip3p-H" class="HW" element="H" mass="1.007947"/>
 </AtomTypes>
 <Residues>
  <Residue name="HOH">
   <Atom name="O" type="tip3p-O" charge="-0.834"/>
   <Atom name="H1" type="tip3p-H" charge="0.417"/>
   <Atom name="H2" type="tip3p-H" charge="0.417"/>
   <Bond from="0" to="1"/>
   <Bond from="0" to="2"/>
  </Residue>
 </Residues>
 <NonbondedForce coulomb14scale="0.833333" lj14scale="0.5">
  <UseAttributeFromResidue name="charge"/>
  <Atom type="tip3p-O" sigma="0.315" epsilon="0.635"/>
  <Atom type="tip3p-H" sigma="1" epsilon="0"/>
 </NonbondedForce>
</ForceField>"""
        ff = ForceField(StringIO(xml))

        # Build a water box.
        modeller = Modeller(Topology(), [])
        modeller.addSolvent(ff, boxSize=Vec3(3, 3, 3)*nanometers)

        # Create a system and make sure all nonbonded parameters are correct.
        system = ff.createSystem(modeller.topology)
        nonbonded = [f for f in system.getForces() if isinstance(f, NonbondedForce)][0]
        atoms = list(modeller.topology.atoms())
        for i in range(len(atoms)):
            params = nonbonded.getParticleParameters(i)
            if atoms[i].element == elem.oxygen:
                self.assertEqual(params[0], -0.834*elementary_charge)
                self.assertEqual(params[1], 0.315*nanometers)
                self.assertEqual(params[2], 0.635*kilojoule_per_mole)
            else:
                self.assertEqual(params[0], 0.417*elementary_charge)
                self.assertEqual(params[1], 1.0*nanometers)
                self.assertEqual(params[2], 0.0*kilojoule_per_mole)

    def test_residueTemplateGenerator(self):
        """Test the ability to add residue template generators to parameterize unmatched residues."""
        def simpleTemplateGenerator(forcefield, residue):
            """\
            Simple residue template generator.
            This implementation uses the programmatic API to define residue templates.

            NOTE: We presume we have already loaded the force definitions into ForceField.
            """
            # Generate a unique prefix name for generating parameters.
            from uuid import uuid4
            template_name = uuid4()
            # Create residue template.
            from simtk.openmm.app.forcefield import _createResidueTemplate
            template = _createResidueTemplate(residue) # use helper function
            template.name = template_name # replace template name
            for (template_atom, residue_atom) in zip(template.atoms, residue.atoms()):
                template_atom.type = 'XXX' # replace atom type
            # Register the template.
            forcefield.registerResidueTemplate(template)

            # Signal that we have successfully parameterized the residue.
            return True

        # Define forcefield parameters used by simpleTemplateGenerator.
        # NOTE: This parameter definition file will currently only work for residues that either have
        # no external bonds or external bonds to other residues parameterized by the simpleTemplateGenerator.
        simple_ffxml_contents = """
<ForceField>
 <AtomTypes>
  <Type name="XXX" class="XXX" element="C" mass="12.0"/>
 </AtomTypes>
 <HarmonicBondForce>
  <Bond type1="XXX" type2="XXX" length="0.1409" k="392459.2"/>
 </HarmonicBondForce>
 <HarmonicAngleForce>
  <Angle type1="XXX" type2="XXX" type3="XXX" angle="2.09439510239" k="527.184"/>
 </HarmonicAngleForce>
 <NonbondedForce coulomb14scale="0.833333" lj14scale="0.5">
  <Atom type="XXX" charge="0.000" sigma="0.315" epsilon="0.635"/>
 </NonbondedForce>
</ForceField>"""

        #
        # Test where we generate parameters for only a ligand.
        #

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'T4-lysozyme-L99A-p-xylene-implicit.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('amber99sb.xml', 'tip3p.xml', StringIO(simple_ffxml_contents))
        # Add the residue template generator.
        forcefield.registerTemplateGenerator(simpleTemplateGenerator)
        # Parameterize system.
        system = forcefield.createSystem(pdb.topology, nonbondedMethod=NoCutoff)
        # TODO: Test energies are finite?

        #
        # Test for a few systems where we generate all parameters.
        #

        tests = [
            { 'pdb_filename' : 'alanine-dipeptide-implicit.pdb', 'nonbondedMethod' : NoCutoff },
            { 'pdb_filename' : 'lysozyme-implicit.pdb', 'nonbondedMethod' : NoCutoff },
            { 'pdb_filename' : 'alanine-dipeptide-explicit.pdb', 'nonbondedMethod' : CutoffPeriodic },
            ]

        # Test all systems with separate ForceField objects.
        for test in tests:
            # Load the PDB file.
            pdb = PDBFile(os.path.join('systems', test['pdb_filename']))
            # Create a ForceField object.
            forcefield = ForceField(StringIO(simple_ffxml_contents))
            # Add the residue template generator.
            forcefield.registerTemplateGenerator(simpleTemplateGenerator)
            # Parameterize system.
            system = forcefield.createSystem(pdb.topology, nonbondedMethod=test['nonbondedMethod'])
            # TODO: Test energies are finite?

        # Now test all systems with a single ForceField object.
        # Create a ForceField object.
        forcefield = ForceField(StringIO(simple_ffxml_contents))
        # Add the residue template generator.
        forcefield.registerTemplateGenerator(simpleTemplateGenerator)
        for test in tests:
            # Load the PDB file.
            pdb = PDBFile(os.path.join('systems', test['pdb_filename']))
            # Parameterize system.
            system = forcefield.createSystem(pdb.topology, nonbondedMethod=test['nonbondedMethod'])
            # TODO: Test energies are finite?

    def test_getUnmatchedResidues(self):
        """Test retrieval of list of residues for which no templates are available."""

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'T4-lysozyme-L99A-p-xylene-implicit.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('amber99sb.xml', 'tip3p.xml')
        # Get list of unmatched residues.
        unmatched_residues = forcefield.getUnmatchedResidues(pdb.topology)
        # Check results.
        self.assertEqual(len(unmatched_residues), 1)
        self.assertEqual(unmatched_residues[0].name, 'TMP')
        self.assertEqual(unmatched_residues[0].id, '163')

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'ala_ala_ala.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('tip3p.xml')
        # Get list of unmatched residues.
        unmatched_residues = forcefield.getUnmatchedResidues(pdb.topology)
        # Check results.
        self.assertEqual(len(unmatched_residues), 3)
        self.assertEqual(unmatched_residues[0].name, 'ALA')
        self.assertEqual(unmatched_residues[0].chain.id, 'X')
        self.assertEqual(unmatched_residues[0].id, '1')

    def test_ggenerateTemplatesForUnmatchedResidues(self):
        """Test generation of blank forcefield residue templates for unmatched residues."""
        #
        # Test where we generate parameters for only a ligand.
        #

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'nacl-water.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('tip3p.xml')
        # Get list of unmatched residues.
        unmatched_residues = forcefield.getUnmatchedResidues(pdb.topology)
        [templates, residues] = forcefield.generateTemplatesForUnmatchedResidues(pdb.topology)
        # Check results.
        self.assertEqual(len(unmatched_residues), 24)
        self.assertEqual(len(residues), 2)
        self.assertEqual(len(templates), 2)
        unique_names = set([ residue.name for residue in residues ])
        self.assertTrue('HOH' not in unique_names)
        self.assertTrue('NA' in unique_names)
        self.assertTrue('CL' in unique_names)
        template_names = set([ template.name for template in templates ])
        self.assertTrue('HOH' not in template_names)
        self.assertTrue('NA' in template_names)
        self.assertTrue('CL' in template_names)

        # Define forcefield parameters using returned templates.
        # NOTE: This parameter definition file will currently only work for residues that either have
        # no external bonds or external bonds to other residues parameterized by the simpleTemplateGenerator.
        simple_ffxml_contents = """
<ForceField>
 <AtomTypes>
  <Type name="XXX" class="XXX" element="C" mass="12.0"/>
 </AtomTypes>
 <HarmonicBondForce>
  <Bond type1="XXX" type2="XXX" length="0.1409" k="392459.2"/>
 </HarmonicBondForce>
 <HarmonicAngleForce>
  <Angle type1="XXX" type2="XXX" type3="XXX" angle="2.09439510239" k="527.184"/>
 </HarmonicAngleForce>
 <NonbondedForce coulomb14scale="0.833333" lj14scale="0.5">
  <Atom type="XXX" charge="0.000" sigma="0.315" epsilon="0.635"/>
 </NonbondedForce>
</ForceField>"""

        #
        # Test the pre-geenration of missing residue template for a ligand.
        #

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'T4-lysozyme-L99A-p-xylene-implicit.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('amber99sb.xml', 'tip3p.xml', StringIO(simple_ffxml_contents))
        # Get list of unique unmatched residues.
        [templates, residues] = forcefield.generateTemplatesForUnmatchedResidues(pdb.topology)
        # Add residue templates to forcefield.
        for template in templates:
            # Replace atom types.
            for atom in template.atoms:
                atom.type = 'XXX'
            # Register the template.
            forcefield.registerResidueTemplate(template)
        # Parameterize system.
        system = forcefield.createSystem(pdb.topology, nonbondedMethod=NoCutoff)
        # TODO: Test energies are finite?

    def test_getMatchingTemplates(self):
        """Test retrieval of list of templates that match residues in a topology."""

        # Load the PDB file.
        pdb = PDBFile(os.path.join('systems', 'ala_ala_ala.pdb'))
        # Create a ForceField object.
        forcefield = ForceField('amber99sb.xml')
        # Get list of matching residue templates.
        templates = forcefield.getMatchingTemplates(pdb.topology)
        # Check results.
        residues = [ residue for residue in pdb.topology.residues() ]
        self.assertEqual(len(templates), len(residues))
        self.assertEqual(templates[0].name, 'NALA')
        self.assertEqual(templates[1].name, 'ALA')
        self.assertEqual(templates[2].name, 'CALA')

class AmoebaTestForceField(unittest.TestCase):
    """Test the ForceField.createSystem() method with the AMOEBA forcefield."""

    def setUp(self):
        """Set up the tests by loading the input pdb files and force field
        xml files.

        """

        self.pdb1 = PDBFile('systems/amoeba-ion-in-water.pdb')
        self.forcefield1 = ForceField('amoeba2013.xml')
        self.topology1 = self.pdb1.topology


    def test_NonbondedMethod(self):
        """Test all five options for the nonbondedMethod parameter."""

        methodMap = {NoCutoff:AmoebaMultipoleForce.NoCutoff,
                     PME:AmoebaMultipoleForce.PME}

        for method in methodMap:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                  nonbondedMethod=method)
            forces = system.getForces()
            self.assertTrue(any(isinstance(f, AmoebaMultipoleForce) and
                                f.getNonbondedMethod()==methodMap[method]
                                for f in forces))
    def test_Cutoff(self):
        """Test to make sure the nonbondedCutoff parameter is passed correctly."""

        cutoff_distance = 0.7*nanometer
        for method in [NoCutoff, PME]:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                   nonbondedMethod=method,
                                                   nonbondedCutoff=cutoff_distance,
                                                   constraints=None)

            for force in system.getForces():
                if isinstance(force, AmoebaVdwForce):
                    self.assertEqual(force.getCutoff(), cutoff_distance)
                if isinstance(force, AmoebaMultipoleForce):
                    self.assertEqual(force.getCutoffDistance(), cutoff_distance)

    def test_DispersionCorrection(self):
        """Test to make sure the nonbondedCutoff parameter is passed correctly."""

        for useDispersionCorrection in [True, False]:
            system = self.forcefield1.createSystem(self.pdb1.topology,
                                                   nonbondedMethod=PME,
                                                   useDispersionCorrection=useDispersionCorrection)

            for force in system.getForces():
                if isinstance(force, AmoebaVdwForce):
                    self.assertEqual(useDispersionCorrection, force.getUseDispersionCorrection())

    def test_RigidWater(self):
        """Test that AMOEBA creates rigid water with the correct geometry."""

        system = self.forcefield1.createSystem(self.pdb1.topology, rigidWater=True)
        constraints = dict()
        for i in range(system.getNumConstraints()):
            p1,p2,dist = system.getConstraintParameters(i)
            if p1 < 3:
                constraints[(min(p1,p2), max(p1,p2))] = dist.value_in_unit(nanometers)
        hoDist = 0.09572
        hohAngle = 108.50*math.pi/180.0
        hohDist = math.sqrt(2*hoDist**2 - 2*hoDist**2*math.cos(hohAngle))
        self.assertAlmostEqual(constraints[(0,1)], hoDist)
        self.assertAlmostEqual(constraints[(0,2)], hoDist)
        self.assertAlmostEqual(constraints[(1,2)], hohDist)

    def test_Forces(self):
        """Compute forces and compare them to ones generated with a previous version of OpenMM to ensure they haven't changed."""

        pdb = PDBFile('systems/alanine-dipeptide-implicit.pdb')
        forcefield = ForceField('amoeba2013.xml', 'amoeba2013_gk.xml')
        system = forcefield.createSystem(pdb.topology, polarization='direct')
        integrator = VerletIntegrator(0.001)
        context = Context(system, integrator)
        context.setPositions(pdb.positions)
        state1 = context.getState(getForces=True)
        with open('systems/alanine-dipeptide-amoeba-forces.xml') as input:
            state2 = XmlSerializer.deserialize(input.read())
        for f1, f2, in zip(state1.getForces().value_in_unit(kilojoules_per_mole/nanometer), state2.getForces().value_in_unit(kilojoules_per_mole/nanometer)):
            diff = norm(f1-f2)
            self.assertTrue(diff < 0.1 or diff/norm(f1) < 1e-3)

    def test_Wildcard(self):
        """Test that PeriodicTorsionForces using wildcard ('') for atom types / classes in the ffxml are correctly registered"""

        # Use wildcards in types
        xml = """
<ForceField>
 <AtomTypes>
  <Type name="C" class="C" element="C" mass="12.010000"/>
  <Type name="O" class="O" element="O" mass="16.000000"/>
 </AtomTypes>
 <PeriodicTorsionForce>
  <Proper type1="" type2="C" type3="C" type4="" periodicity1="2" phase1="3.141593" k1="15.167000"/>
  <Improper type1="C" type2="" type3="" type4="O" periodicity1="2" phase1="3.141593" k1="43.932000"/>
 </PeriodicTorsionForce>
</ForceField>"""

        ff = ForceField(StringIO(xml))

        self.assertEqual(len(ff._forces[0].proper), 1)
        self.assertEqual(len(ff._forces[0].improper), 1)

       # Use wildcards in classes
        xml = """
<ForceField>
 <AtomTypes>
  <Type name="C" class="C" element="C" mass="12.010000"/>
  <Type name="O" class="O" element="O" mass="16.000000"/>
 </AtomTypes>
 <PeriodicTorsionForce>
  <Proper class1="" class2="C" class3="C" class4="" periodicity1="2" phase1="3.141593" k1="15.167000"/>
  <Improper class1="C" class2="" class3="" class4="O" periodicity1="2" phase1="3.141593" k1="43.932000"/>
 </PeriodicTorsionForce>
</ForceField>"""

        ff = ForceField(StringIO(xml))

        self.assertEqual(len(ff._forces[0].proper), 1)
        self.assertEqual(len(ff._forces[0].improper), 1)

    def test_ScalingFactorCombining(self):
        """ Tests that FFs can be combined if their scaling factors are very close """
        forcefield = ForceField('amber99sb.xml', os.path.join('systems', 'test_amber_ff.xml'))
        # This would raise an exception if it didn't work

if __name__ == '__main__':
    unittest.main()
