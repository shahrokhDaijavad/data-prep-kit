debug=$1
dbg_suffix=.dev7
# Assume this file is in the reporoot/scripts directory
reporoot=$(dirname $0)/..
cd $reporoot

DEFAULT_BRANCH=dev

# Make sure we're starting from the base branch
git fetch
git checkout $DEFAULT_BRANCH 

# Get the currently defined version w/o any suffix.  This is the next release version
version=$(make DPK_VERSION_SUFFIX= show-version)
echo Building release branch and tag for version $version

if [ -z "$debug" ]; then
    tag=v$version
else
    tag=test$version
fi

# Create a new branch for this version and switch to it
release_branch=releases/$tag
if [ ! -z "$debug" ]; then
    # delete local tag and branch
    git tag --delete $tag
    git branch --delete $release_branch
    # delete remote tag and branch
    git push --delete origin $tag
    git push --delete origin $release_branch
fi
echo Creating $release_branch branch
git checkout -b $release_branch 

# Remove the release suffix in this branch
# Apply the unsuffixed version to the repo and check it into this release branch
if [ -z "$debug" ]; then
    cat .make.versions | sed -e 's/^DPK_VERSION_SUFFIX.*/DPK_VERSION_SUFFIX=/' > tt
    mv tt .make.versions
else
    cat .make.versions | sed -e "s/^DPK_VERSION_SUFFIX.*/DPK_VERSION_SUFFIX=$dbg_suffix/" > tt
    mv tt .make.versions
fi
# Apply the version change to all files in the repo 
echo Applying $version to $release_branch branch 
make set-versions > /dev/null

# Commit the changes to the release branch and tag it
git status
echo Committing and pushing version changes in $release_branch branch. 
git commit --no-verify -s -a -m "Cut release $version"
git push --set-upstream origin $release_branch 
echo Committing and pushing tag $tag in $release_branch branch
git tag -a -s -m "Cut release $version" $tag 
git push origin $tag 

# Now create and push a new branch from which we will PR into main to update the version 
next_version_branch=release_next_pending
echo Creating $next_version_branch branch for PR request back to main for version upgrade
git checkout -b $next_version_branch 
git commit --no-verify -s -a -m "Branch to PR back into $DEFAULT_BRANCH holding the next version"
git push --set-upstream origin $next_version_branch

# Change to the next development version (bumped minor version with suffix).
micro=$(cat .make.versions | grep '^DPK_MICRO_VERSION=' | sed -e 's/DPK_MICRO_VERSION=\([0-9]*\).*/\1/') 
micro=$(($micro + 1))
cat .make.versions | sed -e "s/^DPK_MICRO_VERSION=.*/DPK_MICRO_VERSION=$micro/"  \
 			 -e "s/^DPK_VERSION_SUFFIX=.*/DPK_VERSION_SUFFIX=.dev0/"  > tt
mv tt .make.versions
# Apply the version change to all files in the repo 
next_version=$(make show-version)
echo Applying updated version $next_version to $next_version_branch branch
make set-versions > /dev/null

# Push the version change back to the origin
if [ -z "$debug" ]; then
    echo Committing and pushing version $next_version to $next_version_branch branch.
    git commit --no-verify -s -a -m "Bump micro version to $next_version after cutting release $version into branch $release_branch"
    #git diff origin/$next_version_branch $next_version_branch 
    git push origin
    echo Please go to https://github.com/IBM/data-prep-kit/pulls and 
    echo create a new pull request from the $next_version_branch branch back into $DEFAULT_BRANCH branch. 
else
    git status
    echo In non-debug mode, the above diffs would have been committed to the $next_version_branch branch
fi
